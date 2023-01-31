#!/usr/bin/python3

# testdial.py
#
# 

# This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public 
# License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.
# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty 
# of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.
# You should have received a copy of the GNU General Public License along with this program. If not, 
# see <https://www.gnu.org/licenses/>.

# Having said that, it would be great to know if this software gets used. If you want, buy me a coffee, or send me some hardware
# Darryl Smith, VK2TDS. darryl@radio-active.net.au Copyright 2023

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




HOST = "127.0.0.1"  # The server's hostname or IP address
PORT = 4532  # The port used by the server

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.connect((HOST, PORT))
    s.sendall(b'+\\get_vfo_info VFOA\n')
    data = s.recv(1024)

print(f"Received {data!r}")