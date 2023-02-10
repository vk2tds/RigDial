#!/usr/bin/python3

# rigdial.py
#
# Device driver for the Contour Xpress Multimedia Controller, to control an Icom IC-7300 HF radio
# via Flrig using the XML-RPC interface. It also sends VFO frequency, split and mode to MacLoggerDX
#
# This code was developed for MacOS but should work under Windows and Linux

# This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public 
# License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.
# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty 
# of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.
# You should have received a copy of the GNU General Public License along with this program. If not, 
# see <https://www.gnu.org/licenses/>.

# Having said that, it would be great to know if this software gets used. If you want, buy me a coffee, or send me some hardware
# Darryl Smith, VK2TDS. darryl@radio-active.net.au Copyright 2023

import hid                  # For some reason I needed to add the path to this library in my .zprofile 
import binascii
import pprint
import time
import sys
import socket
import logging
import logging.handlers
import xmlrpc.client

from subprocess import Popen, PIPE
from threading import Thread

# MAYBE, we can register a callback to be notified about device
# add/remove (https://github.com/pyusb/pyusb/pull/160)
from usb import core
from usb import util


class Freq():
    def __init__(self):

        self.freq = {"160M": 1840000,
                "80M": 3573000,
                "40M": 7074000,
                "30M": 10136000,
                "20M": 14074000,
                "17M": 18100000,
                "15M": 21074000,
                "12M": 24915000,
                "10M": 28075000,
                "6M": 50313000}

        self.freq_order = ["160M", "80M", "40M", "30M", "20M", "17M", "15M", "12M", "10M", "6M"]

    def getBand(self, f):
        if f < 2 * 1000000:
            return ("160M")
        if f < 4 * 1000000:
            return ("80M")
        if f < 8 * 1000000:
            return ("40M")
        if f < 12 * 1000000:
            return ("30M")
        if f < 16 * 1000000:
            return ("20M")
        if f < 19 * 1000000:
            return ("17M") 
        if f < 23 * 1000000:
            return ("15M")
        if f < 26 * 1000000:
            return ("12M")
        if f < 30 * 1000000:
            return ("10M")
        return ("6M")       



class Wheel():
    # This class will do callbacks when data is receieved.

    def __init__(self):
        #self.supported_devices = supported_devices
        self.devices_to_bind = {}

        self.shuttle_value = 0 
        self.jog_value = None
        self.jog_time = None
        self.buttons = [False, False, False, False, False] 

        self.jog_callbacks = []
        self.shuttle_callbacks = []
        self.button_callbacks = []

        # some info can be gathered by:
        #   $ lsusb -v
        # or device specific:
        #   $ lsusb -d vid:pid -v
        self.supported_devices = { # Two lines to show how to add another one later for other models
            'Contour Design': {'vendor_id': '0b33',
                    'devices': [
                        {'name': 'ShuttleXpress',
                        'product_id': '0020'}
                        ]
                    },
            'Dummy': {'vendor_id': '0123',
                            'devices': [
                                {'name': 'Dummy Product',
                                'product_id': 'fedb'}
                            ]
                            }
        }


            # we can enumarate with vendor_id and product_id as well, useful after some
            # type of hotplug event
        for dev in hid.enumerate():
            manufacturer = dev.get('manufacturer_string')
            product = dev.get('product_string')
            if manufacturer in self.supported_devices:
                for device in self.supported_devices[manufacturer]['devices']:
                    vendor_id = self.str_to_int(
                        self.supported_devices[manufacturer]['vendor_id'])

                    if product == device['name'] and \
                        self.dec_to_hex(dev.get('product_id')) == device['product_id']:
                        product_id = self.str_to_int(device['product_id'])
                        # 3 == hid, 1 == audio
                        usb_device = core.find(find_all=True,
                                       custom_match=self.find_class(3),
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


    def dec_to_hex(self, value):
        return (format (value, '04x'))

    def str_to_int(self, value):
        return int(value, base=16)

    def str_to_hex(self, value):
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
    #TODO: Rename Telnet to something more appropriate

    def __init__(self, endpoint, port):
        self.endpoint = endpoint
        self.port = port
        self.connected = False
        self.s = None
        self.inThread = False



    def connect (self):
        self.s = xmlrpc.client.ServerProxy('http://127.0.0.1:12345')
        self.connected = True
        log.info ("XML-RPC Connected")


    #TODO: Look at this
    def loop (self):
        True
        
    #TODO: Look at this    
    def go(self):
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

    @property
    def split (self):
        while self.inThread:
          True
        self.inThread = True
        r = float(self.s.rig.get_split())
        self.inThread = False
        return r
        
    @split.setter
    def split(self, s):
        while self.inThread:
          True
        self.inThread = True
        r = self.s.rig.set_verify_split(int(s))
        self.inThread = False
        return r


class rigctldFake:
    # This class is implements a very minor subset of the HamLib TCP server. It only implements a single HamLib command,
    # and even then, only returns some of the information that would normally be supplied by the server. Specifically, the
    # server accepts the 'get_vfo_info VFOA' command, with specific spacing and linefeed. It returns the current VFO 
    # frequency, mode and split. These parameters are injected into the class from outside - generally by polling the 
    # Fldigi server. 

    def __init__(self, endpoint, port):
      self.endpoint = endpoint
      self.port = port
      self.vfo = "5"
      self.mode = "USB-D"
      self.split = "5"
      self.taint = True     # When this is True we need to send updated VFO to MacLoggerDX. No longer used


    def on_new_client(self, clientsocket, addr):
        while True:
            try:
                data = clientsocket.recv(1024)
                #receieve     b'+\\get_vfo_info VFOA\n'
                #send b'get_vfo_info: VFOA\nFreq: 28074000\nMode: PKTUSB\nWidth: 3000\nSplit: 0\nSatMode: 0\nRPRT 0\n'
                if data == b'+\\get_vfo_info VFOA\n':
                    direct = b'get_vfo_info: VFOA\nFreq: %s\nMode: %s\nSplit: %s\nRPRT 0\n' % ( \
                        bytes(str(self.vfo),  encoding='utf-8'), \
                        bytes(self.mode,  encoding='utf-8'), \
                        bytes(str(self.split),  encoding='utf-8'))
                    clientsocket.sendall (direct)
            except socket.error as exc:
                log.info( "Caught exception socket.error : %s" % (exc))
        clientsocket.close()

        

    def listen(self):
        self.s = socket.socket()
        self.s.bind((self.endpoint, self.port))
        self.s.listen (10) # I have a number here to hopefully stop Connection Reset By Peer errors. https://stackoverflow.com/questions/64412521/connection-reset-by-peer-in-python-when-socket-listen-backlog-is-small
        while True:
            c, addr = self.s.accept()
            Thread (target=self.on_new_client, args=(c, addr) ).start()
            #thread.start_new_thread (self.on_new_client, (c, addr))
        self.s.close


    def go(self):
      Thread (target=self.listen).start()
      True


def get_vfo(r, t):
    # Take the 'telnet' radio settings and send them to the 'rigctldFake' class. 
    # We no longer use r.taint, but set it just in case
    temp = t.vfo
    if r.vfo != temp:
        r.vfo = temp
        r.taint = True
    temp = t.mode
    if r.mode != temp:
        r.mode = temp
        r.taint = True
    temp = t.split
    if t.split != temp:
        r.split = temp
        r.taint = True
 
    if r.taint:
        # save the frequency for this band in a variable 
        band = f.getBand(r.vfo)
        f.freq [band] = r.vfo








def button(self, button_number, value):
    
    # This handler is ONLY when button presses are used without the JOG or SHUTTLE wheel
    #
    log.info ("Event Button %d state %d" % (button_number, value))
    # Voice PTT whilst button 0 is pressed.
    if (button_number == 0) & (value == 0):
        log.debug ("PTT Off")
        t.ptt = 0
    if (button_number == 0) & (value == 1):
        log.debug ("PTT On")
        t.ptt = 1
    if (button_number == 0) & (value == 1):
        log.debug ("Nothing happens")
    if (button_number == 2) & (value == 1):
        # Toggle the minimum frequency change between 10 and 1000, on button down
        if settings.minFreqChange == settings.freqChangeBig:
            settings.minFreqChange = settings.freqChangeSmall
        else:
            settings.minFreqChange = settings.freqChangeBig
        log.info ("Minimum frequency change is now %d" % (settings.minFreqChange))
        #t.send(b"+t\n")
    if (button_number == 3):
        log.debug ("Button index 3 is controlled by JOG - Mic Gain")
    if (button_number == 4):
        log.debug ("Button index 4 is controlled by JOG - Power")
        

maxShuttle = 0
direction = 0
def shuttle(self, value):
    global maxShuttle
    global direction
    log.info ("Event Shuttle value %d" %(value))

    if value == 0:
        if maxShuttle < 0:
            direction = -1
        else:
            direction = 1
        maxShuttle = 0
        currentF = t.vfo
        currentBand = f.getBand (currentF)
        
        index = f.freq_order.index (currentBand)
        newBand = f.freq_order[(index + direction) % len(f.freq_order)]
        log.info ("New Band - %s" % (newBand))
        t.vfo = f.freq[newBand]
        t.split = 0

    if abs(value) > abs(maxShuttle):
        maxShuttle = value       


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
        return

    # Assuming NO BUTTONS ARE PRESSED!!!
    vfo = t.vfo
    # Depending on how fast the Jog Wheel is moving, we use a multiplier to make the frequency change bigger. 
    mult = 1.0
    if abs(velocity) < 30:
        mult = 1.0
    elif abs(velocity) < 60:
        mult = 4.0
    elif abs(velocity) < 90:
        mult = 9.0
    else:
        mult = 15.0
    vfo = vfo + ( settings.minFreqChange * delta_value * mult)
    log.info ("Setting new VFO frequency %f" % (vfo))
    t.vfo = vfo




class Settings:
    def __init__(self):
        self.MacLoggerDX = True
        self.HamLibIncomingHost = '127.0.0.1'
        self.HamLibIncomingPort = 4532
        self.FlrigDestHost = '127.0.0.1'
        self.FlrigDestPort = 12345
        self.freqChangeSmall = 10
        self.freqChangeBig = 1000
        self.minFreqChange = self.freqChangeSmall

if __name__ == "__main__":

    settings = Settings()
    f = Freq()

    # Change root logger level from WARNING (default) to NOTSET in order for all messages to be delegated.
    logging.getLogger().setLevel(logging.NOTSET)

    # Add stdout handler, with level INFO
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    formater = logging.Formatter('%(name)-13s: %(levelname)-8s %(message)s')
    console.setFormatter(formater)
    logging.getLogger().addHandler(console)

    log = logging.getLogger("app." + __name__)

    log.info ("Jog: Change VFO Frequency. Push Button 4 or 5 and whilst turning to adjust Mic Gain and Power")
    log.info ("Shuttle: Unused")
    log.info ("Button 1: Push and hold for PTT")
    log.info ("Button 2: Unused")
    log.info ("Button 3: Toggle between 10Hz and 1000Hz minimum VFO changes on Jog")
    log.info ("Button 4: Push whilst Jog to adjust Mic Gain")
    log.info ("Button 5: Push whilst Jog to adjust Power")
#

    #log.debug('Debug message, should only appear in the file.')
    #log.info('Info message, should appear in file and stdout.')
    #log.warning('Warning message, should appear in file and stdout.')
    #log.error('Error message, should appear in file and stdout.')





    w = Wheel ()
    w.on_button (button)
    w.on_shuttle (shuttle)
    w.on_jog (jog)
    w.go()
    
    if settings.MacLoggerDX:
        # Only create the fake rigctld if we are running MacLoggerDX
        r = rigctldFake (settings.HamLibIncomingHost, settings.HamLibIncomingPort)
        r.go()


    log.info ("Starting")
    t = Telnet (settings.FlrigDestHost, settings.FlrigDestPort)
    t.connect()
    


    while 1==1:
        if settings.MacLoggerDX:
            get_vfo(r, t) # Only poll the VFO on the radio if we are connected to MacLoggerDX
        time.sleep (1)        
        