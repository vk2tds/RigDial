# hid==1.0.4
# pyusb==1.0.2
# NOTE: should install hidpai (brew/package manager)
import hid
import binascii
import pprint
import time
import sys
import socket
from threading import Thread
import logging
import logging.handlers
from subprocess import Popen, PIPE

import xmlrpc.client

# MAYBE, we can register a callback to be notified about device
# add/remove (https://github.com/pyusb/pyusb/pull/160)
from usb import core
from usb import util






def dec_to_hex(value):
    return (format (value, '04x'))


def str_to_int(value):
    return int(value, base=16)


def str_to_hex(value):
    return hex(str_to_int(value))


class find_class(object):
    def __init__(self, class_):
        self._class = class_

    def __call__(self, device):
        if device.bDeviceClass == self._class:
            return True

        for cfg in device:
            intf = util.find_descriptor(cfg, bInterfaceClass=self._class)
            if intf is not None:
                return True

        return False


# some info can be gathered by:
#   $ lsusb -v
# or device specific:
#   $ lsusb -d vid:pid -v


class Wheel():
    def __init__(self, supported_devices):
        self.supported_devices = supported_devices
        self.devices_to_bind = {}

        self.shuttle_value = 0 
        self.jog_value = None
        self.jog_time = None
        self.buttons = [False, False, False, False, False] 

        self.jog_callbacks = []
        self.shuttle_callbacks = []
        self.button_callbacks = []

            # we can enumarate with vendor_id and product_id as well, useful after some
            # type of hotplug event
        for dev in hid.enumerate():
            manufacturer = dev.get('manufacturer_string')
            product = dev.get('product_string')
            if manufacturer in self.supported_devices:
                for device in supported_devices[manufacturer]['devices']:
                    vendor_id = str_to_int(
                        supported_devices[manufacturer]['vendor_id'])

                    if product == device['name'] and \
                        dec_to_hex(dev.get('product_id')) == device['product_id']:
                        product_id = str_to_int(device['product_id'])
                        # 3 == hid, 1 == audio
                        usb_device = core.find(find_all=True,
                                       custom_match=find_class(3),
                                       idVendor=vendor_id,
                                       idProduct=product_id)

                    # differentiate two devices with same vid:pid: u.bus, u.address
                    # https://github.com/pyusb/pyusb/blob/master/docs/tutorial.rst#dealing-with-multiple-identical-devices:
                    usb_device = [x for x in usb_device][0]

                    # bInterfaceProtocol 0 (0 == None, 1 == Keyboard, 2 == Mouse)
                    # iInterface 7?
                    for conf in usb_device:
                        for interface in conf:
                            if interface.bInterfaceProtocol == 0 and \
                                    interface.bInterfaceNumber == dev.get(
                                    'interface_number'):
                                # this will not happen, as we will call add_device
                                # instead
                                self.devices_to_bind.setdefault("%s %s" %
                                                           (manufacturer, product),
                                                           []).\
                                    append({'path': dev.get('path'),
                                            'packet_size': interface[0].
                                            wMaxPacketSize}
                                           )

                    s = format (self.devices_to_bind)
                    log.info ("Devices to bind: %s" % (s))

    def on_button(self, callback):
        self.button_callbacks.append(callback)
        
    def on_shuttle(self, callback):
        self.shuttle_callbacks.append(callback)
        
    def on_jog(self, callback):
        self.jog_callbacks.append(callback)
        

    def button(self, button_number, value):
        if self.button_callbacks is not None:
            for callback in self.button_callbacks:
                callback(self, button_number, value)


    def shuttle(self, value):
        if self.button_callbacks is not None:
            for callback in self.shuttle_callbacks:
                callback(self, value)
        
    def jog (self, value, delta_value, delta_time, velocity):
        if self.jog_callbacks is not None:
            for callback in self.jog_callbacks:
                callback(self, value, delta_value, delta_time, velocity)

    # open a device and read it's data
    # on linux we can open hidraw directly; check if we can do it on macos as well
    def read_device(self, path, packet_size):
        d = hid.Device(path=path)

        while True:
            # macos keep reading "0000000000000000" (or "0100000000000000") while
            # idle
            data = binascii.hexlify(d.read(packet_size)).decode()
            x = int (data, 16)

            if (x & 0x1000):
                if self.buttons[0] == False:
                    self.buttons[0] = True
                    self.button(0, self.buttons[0])
            else:
                if self.buttons[0] == True:
                    self.buttons[0] = False
                    self.button(0, self.buttons[0]) 
            if (x & 0x2000):
                if self.buttons[1] == False:
                    self.buttons[1] = True
                    self.button(1, self.buttons[1])
            else:
                if self.buttons[1] == True:
                    self.buttons[1] = False
                    self.button(1, self.buttons[1]) 
            if (x & 0x4000):
                if self.buttons[2] == False:
                    self.buttons[2] = True
                    self.button(2, self.buttons[2])
            else:
                if self.buttons[2] == True:
                    self.buttons[2] = False
                    self.button(2, self.buttons[2]) 
            if (x & 0x8000):
                if self.buttons[3] == False:
                    self.buttons[3] = True
                    self.button(3, self.buttons[3])
            else:
                if self.buttons[3] == True:
                    self.buttons[3] = False
                    self.button(3, self.buttons[3]) 
            if (x & 0x0001):
                if self.buttons[4] == False:
                    self.buttons[4] = True
                    self.button(4, self.buttons[4])
            else:
                if self.buttons[4] == True:
                    self.buttons[4] = False
                    self.button(4, self.buttons[4]) 
            shuttle_value = (x & 0x0F00000000) >> 32
            if (shuttle_value > 8):
                shuttle_value = -(16 - shuttle_value)
            if self.shuttle_value != shuttle_value:
                self.shuttle_value = shuttle_value
                self.shuttle (self.shuttle_value)

            jog_value = (x & 0x00FF000000) >> 24

            if self.jog_value == None:
                self.jog_value = jog_value

            if self.jog_time == None:
                self.jog_time = round(time.time()*1000)
            delta_time = round(time.time()*1000) - self.jog_time
            self.jog_time = round(time.time()*1000)            

            if self.jog_value != jog_value:
                delta_value = jog_value - self.jog_value
                if delta_value < -128:
                    delta_value = delta_value + 256
                if delta_value > 120:
                    delta_value = delta_value - 256

                self.jog_value = jog_value

                velocity = (delta_value/delta_time) * 1000 * 3.5



                self.jog (self.jog_value, delta_value, delta_time, velocity)


        d.close()


    def go(self):
        for d in self.devices_to_bind.keys():
            for h in self.devices_to_bind[d]:
                Thread(target=self.read_device, args=(h['path'], h['packet_size'])).start()
        



class Telnet:

    def __init__(self, endpoint, port):
        self.endpoint = endpoint
        self.port = port
        self.connected = False
        self.s = None
        self.inThread = False



    def connect (self):

        #self.s = xmlrpc.client.ServerProxy((self.endpoint, self.port))
        self.s = xmlrpc.client.ServerProxy('http://127.0.0.1:12345')
                
        self.connected = True
        log.info ("Connected")
        #self.send(b'+f\n')
        #Thread (target=self.loop).start()


    def loop (self):
        #while True:
        #    #with self.s:
        #        data = self.s.recv(1024)
        #        log.debug (f"Received {data!r}")
        True
        
        
    def go(self):
        #Thread (target=self.connect).start()
        True


    @property
    def vfo (self):
        while self.inThread:
          True
        self.inThread = True
        r = float(self.s.rig.get_vfo())
        self.inThread = False
        return r
        
    @vfo.setter
    def vfo(self, freq):
        while self.inThread:
          True
        self.inThread = True
        r = self.s.rig.set_vfo(float(freq))
        self.inThread = False
        return r
        
    @property
    def ptt (self):
        while self.inThread:
          True
        self.inThread = True
        r = self.s.rig.get_ptt()
        self.inThread = False
        return r
        
    @ptt.setter
    def ptt (self, state):
        while self.inThread:
          True
        self.inThread = True
        r = self.s.rig.set_verify_ptt(state)
        self.inThread = False
        return r
        
    #@mod_vfoA.setter
    def mod_vfoA(self, mod):
        while self.inThread:
          True
        self.inThread = True
        r = self.s.rig.mod_vfoA (float(mod))
        self.inThread = False
        return r

    #@mod_vfoB.setter
    def mod_vfoB(self, mod):
        while self.inThread:
          True
        self.inThread = True
        r = self.s.rig.mod_vfoB (float(mod))
        self.inThread = False
        return r


    #@mod_vol.setter
    def mod_vol(self, mod):
        while self.inThread:
          True
        self.inThread = True
        r = self.s.rig.mod_vol (float(mod))
        self.inThread = False
        return r

    @property
    def power(self):
        while self.inThread:
          True
        self.inThread = True
        r =  self.s.rig.get_power ()
        self.inThread = False
        return r

    @power.setter
    def power(self, mod):
        while self.inThread:
          True
        self.inThread = True
        r = self.s.rig.set_verify_power (mod)
        self.inThread = False
        return r


    @property
    def mic_gain (self):
        while self.inThread:
          True
        self.inThread = True
        r = self.s.rig.get_micgain()
        self.inThread = False
        return r
        
    @mic_gain.setter
    def mic_gain (self, gain):
        while self.inThread:
          True
        self.inThread = True
        r = self.s.rig.set_verify_micgain(gain)
        self.inThread = False
        return r

    @property
    def mode (self):
        while self.inThread:
          True
        self.inThread = True
        r = self.s.rig.get_mode()
        self.inThread = False
        return r

    @property
    def split (self):
        while self.inThread:
          True
        self.inThread = True
        r = self.s.rig.get_split()
        self.inThread = False
        return r

supported_devices = {
    'Contour Design': {'vendor_id': '0b33',
              'devices': [
                  {'name': 'ShuttleXpress',
                   'product_id': '0020'}
                   ]
              },
    'GN Netcom A/S': {'vendor_id': '0b0e',
                      'devices': [
                          {'name': 'Jabra HANDSET 450',
                           'product_id': '101b'}
                      ]
                      }
}


# Definitions for Keys
#
# Button 1:
#	Push and hold for PTT
# Button 2:
#	Push to toggle between bands, going up. Changes on release
# 	1.8, 3.5, 7, 10, 14, 18, 21, 24, 28, 50
#	If Jog whilst down, ???
# Button 3:
#	Push to toggle between minimum VFO change of 10 Hz or 1000 Hz
# Button 4:
#	Push and hold whilst jog Power
# Button 5:
#	Push and hold whilst jog Mic gain




#minFrequencyChange = 1000

minFreqChange = 1

def button(self, button_number, value):
    global minFreqChange
    # This handler is ONLY when button presses are used without the JOG or SHUTTLE wheel
    #
    log.info ("Event Button %d state %d" % (button_number, value))
    # Voice PTT whilst button 0 is pressed.
    if (button_number == 0) & (value == 0):
        log.debug ("PTT")
        t.ptt = 0
    if (button_number == 0) & (value == 1):
        log.debug ("PTT")
        t.ptt = 1
    if (button_number == 2) & (value == 1):
        # Toggle the minimum frequency change between 10 and 1000, on button down
        if minFreqChange == 1000:
            minFreqChange = 10
        else:
            minFreqChange = 1000
        log.info ("Minimum frequency change is now %d" % (minFreqChange))
        #t.send(b"+t\n")
    if (button_number == 3):
        log.debug ("Button index 3 is controlled by JOG")
    if (button_number == 4):
        log.debug ("Button index 4 is controlled by JOG")
        


def shuttle(self, value):
    log.info ("Event Shuttle value %d" %(value))
        
def jog (self, value, delta_value, delta_time, velocity):
    log.info ("Event Jog Value %d Delta Value %d Delta Time %d Velocity %d" % (value, delta_value, delta_time, velocity))
    if w.buttons[3]:
        pwr = t.power
        pwr = pwr + delta_value
        t.power = pwr
        log.info ("Setting power level to %f" % (pwr))
        return
    if w.buttons[4]:
        mic_gain = t.mic_gain
        log.info ("Setting Mic Gain %f" % (mic_gain))
        mic_gain = mic_gain + delta_value
        t.mic_gain = mic_gain 
    
    # Assuming NO BUTTONS ARE PRESSED!!!
    vfo = t.vfo
    mult = 1
    if abs(velocity) < 30:
        mult = 1
    elif abs(velocity) < 60:
        mult = 4
    elif abs(velocity) < 90:
        mult = 9
    else:
        mult = 15
    vfo = vfo + ( minFreqChange * delta_value * mult)
    log.info ("Setting new VFO frequency %f" % (vfo))
    t.vfo = vfo






class rigctldFake:

    def __init__(self, endpoint, port):
      self.endpoint = endpoint
      self.port = port
      self.vfo = "10.151"
      self.mode = "USB-D"
      self.split = "5"
      

    def MacLoggerDX (self):
      #b'tell application "MacLoggerDX"\n"setVFOandMode "28.074 USB-D"\nsetSplitKhz "1"\nend tell\n'
      #scpt = b'''
      #tell application "MacLoggerDX"
  #	setVFOandMode "18.130 USB"
  #	setSplitKhz "5"
   #   end tell
    #  '''


      v = self.vfo/1000000
      scpt = b'tell application "MacLoggerDX"\n'
      scpt = scpt + (b'setVFOandMode "%s %s"\n') % (bytes(str(v),  encoding='utf-8'), bytes(self.mode,  encoding='utf-8'))
      scpt = scpt + (b'setSplitKhz "%s"\n') % (bytes(str(self.split),  encoding='utf-8'))
      scpt = scpt + b'end tell\n'


      p = Popen(['osascript'] , stdin=PIPE, stdout=PIPE, stderr=PIPE)
      stdout, stderr = p.communicate(scpt)
      #print (p.returncode, stdout, stderr)

      
      
    def listen(self):
      with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((self.endpoint, self.port))
        s.listen()
        conn, addr = s.accept()
        with conn:
          print(f"Connected by {addr}")
          while True:
              data = conn.recv(1024)
              self.MacLoggerDX()
      


      
      
      
      
      
    def go(self):
      Thread (target=self.listen).start()
      
      True
    
    
    
    
    
















if __name__ == "__main__":

    # Change root logger level from WARNING (default) to NOTSET in order for all messages to be delegated.
    logging.getLogger().setLevel(logging.NOTSET)

    # Add stdout handler, with level INFO
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    formater = logging.Formatter('%(name)-13s: %(levelname)-8s %(message)s')
    console.setFormatter(formater)
    logging.getLogger().addHandler(console)

    log = logging.getLogger("app." + __name__)

    #log.debug('Debug message, should only appear in the file.')
    #log.info('Info message, should appear in file and stdout.')
    #log.warning('Warning message, should appear in file and stdout.')
    #log.error('Error message, should appear in file and stdout.')





    w = Wheel (supported_devices)
    w.on_button (button)
    w.on_shuttle (shuttle)
    w.on_jog (jog)



    w.go()
    
    r = rigctldFake ("127.0.0.1", 4532)
    r.go()
    


    log.info ("Starting")
    t = Telnet ('127.0.0.1', 12345)
    t.connect()
    #t.go()
    





    while 1==1:
        r.vfo = t.vfo
        r.mode = t.mode
        r.split = t.split
        time.sleep (1)        
        