#!/usr/bin/env python

# Decoder for weather data of sensors from ELV received with RTL SDR
# Typical usage: 
# rtl_fm -M -f 868.35M -s 160k | ./decode_elv_wde1.py -
# Help:
# ./decode_elv_wde1.py -h

# Copyright 2014 Martin Kompf
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

# References:
# RTL SDR <http://sdr.osmocom.org/trac/wiki/rtl-sdr>
# The weather sensors are manufactured by ELV <http://www.elv.de/>
# Helmut Bayerlein describes the communication protocol <http://www.dc3yc.homepage.t-online.de/protocol.htm>

import sys
import io
import time
import struct
import math
import logging
import argparse

class decoder(object):
  def __init__(self):
    # We are sampling at 160khz (6.25us),
    # and the length of a bit is always 1220us.
    # Therefore the length of the buffer fo a whole bit is 195.2 samples.
    # Round this down to avoid getting the next bit into the buffer
    self.buf = [0] * 190
    self.decoder_state = 'wait'
    self.pulse_len = 0
    self.on_level = 0
    self.sync_count = 0

  def process(self, value):
    x = self.buf.pop(0);
    self.buf.append(value);
    self.pulse_len += 1
    if self.pulse_len <= 190:
      return # buffer not filled

    if self.decoder_state == 'wait':
      self.sync_count = 0
      self.data = []
      self.test_sync0() # search for first sync bit
    else:
      val = self.bitval()
      logging.debug("bitval = {0}".format(val))
      if val == -1:
        logging.warn("Failed to decode bitval");
        self.decoder_state = 'wait'
      elif val == -10:
        if (self.decoder_state == 'data'):
          # end of frame?
          self.decode()
          self.decoder_state = 'wait'
      elif self.decoder_state == 'sync':
        if val == 0:
          # another sync pulse
          self.sync_count += 1
        elif self.sync_count > 6:
          # got the start bit
          self.decoder_state = 'data'
      elif self.decoder_state == 'data':
        self.data.append(val)

  def test_sync0(self):
    # Test if the data in the buffer is the first sync bit
    # This bit consists of high amplitude with 134..137 samples
    # and low amplitude with 58..61 samples
    sh = self.signal(0, 133)
    sl = self.signal(138, 190)
    avh = sh[0];
    rgh = sh[1];
    avl = sl[0];
    rgl = sl[1];

    if avh < rgh or avh < rgl:
      return # average of high signal amplitude should be greater than noise
    
    if avh < avl:
      return # high signal ampl. should be greater than low
    
    # We found a valid sync 0
    self.decoder_state = 'sync'
    self.on_level = (avh+avl)/2
    self.pulse_len = 0
    logging.info("SYNC!")
    logging.debug("avh={0} avl={1}".format(avh, avl))
    return
  
  def signal(self, begin, end):
    # compute average and range (max-min) of a signal(begin..end)
    sm = 0
    mn = 50000
    mx = -50000
    for i in range(begin, end):
      v = self.buf[i]
      sm += v
      mn = min(mn, v)
      mx = max(mx, v)

    if mx > 32500 or mn < -32500:
      logging.error("Clipped signal detected, you should reduce gain of receiver!")
    return [sm/(end-begin), mx-mn] 

  def bitval(self):
    # detect start of bit: the signal should be at off, 
    # so detect a transition to on
    skip = 0
    while skip < 20:
      x = self.buf[skip]
      if x > self.on_level:
        break
      skip += 1

    self.pulse_len = -skip
    logging.debug("skip={0}".format(skip))
    if skip >= 20:
      logging.debug("No starting slope off->on deteced")
      return -10 
    

    # first 58 samples (366 us) always high signal
    # but allow a jitter of 2 samples
    val = -1
    a = self.signal(skip+2, skip+56);
    # Next 78 samples (488 us) either low or high depending on bitval 
    m = self.signal(skip+60, skip+133)
    # last 58 sample should be always low signal
    e = self.signal(skip+138, 190)

    if a[0] > a[1] and a[0] > e[0]:
      if abs(m[0]-a[0]) > abs(m[0]-e[0]):
        val = 1
      else:
        val = 0 

    self.on_level = (a[0]+e[0])/2
    logging.debug("bitval: a={0} m={1} e={2} val={3}".format(a[0], m[0], e[0], val))
    return val
     
  def popbits(self, num):
    val = 0
    if len(self.data) < num:
      logging.warn("data exhausted")
      return 0
    for i in range(0, num): 
      val += self.data.pop(0) << i
    return val

  def decode(self):
    sensor_types = ('Thermo', 'Thermo/Hygro', 'Rain(?)', 'Wind(?)', 'Thermo/Hygro/Baro', 'Luminance(?)', 'Pyrano(?)', 'Kombi')
    sensor_data_count = (5, 8, 5, 8, 12, 6, 6, 14)

    logging.info("DECODE")
    check = 0
    sum = 0
    sensor_type = self.popbits(4) & 7
    if not self.expect_eon():
      return
    check ^= sensor_type
    sum += sensor_type

    # read data as nibbles
    nibble_count = sensor_data_count[sensor_type]
    dec = []
    for i in range(0, nibble_count):
      nibble = self.popbits(4)
      if not self.expect_eon():
        return
      dec.append(nibble)
      check ^= nibble
      sum += nibble

    # check
    if check != 0:
      logging.warn("Check is not 0 but {0}".format(check))
      return

    # sum
    sum_read = self.popbits(4)
    sum += 5
    sum &= 0xF
    if sum_read != sum:
      logging.warn("Sum read is {0} but computed is {1}".format(sum_read, sum))
      return

    print(time.strftime("time: %x %X"))
    print("sensor type: " + sensor_types[sensor_type])
    print("address: {0}".format(dec[0] & 7))

    print("temperature: {0}{1}.{2}".format(("-" if (dec[0]&8) else ''), dec[3]*10+dec[2], dec[1]))

    if sensor_type == 7:
      # Kombisensor
      print("humidity: {0}".format(dec[5]*10+dec[4]))
      print("wind: {0}.{1}".format(dec[8]*10+dec[7], dec[6]))
      print("rain sum: {0}".format(dec[11]*16*16+dec[10]*16+dec[9]))
      print("rain detector: {0}".format(dec[0]&2 == 1))
    if (sensor_type == 1) or (sensor_type == 4):
      # Thermo/Hygro
      print("humidity: {0}.{1}".format(dec[6]*10+dec[5], dec[4]))
    if sensor_type == 4:
      # Thermo/Hygro/Baro
      print("pressure: {0}".format(200+dec[9]*100+dec[8]*10+dec[7]))

    print
      
  def expect_eon(self):
    # check end of nibble (1)
    if self.popbits(1) != 1:
      logging.warn("end of nibble is not 1")
      return False
    return True

def main():
  parser = argparse.ArgumentParser(description='Decoder for weather data of sensors from ELV received with RTL SDR.')
  parser.add_argument('--log', type=str, default='WARN', help='Log level: DEBUG|INFO|WARN|ERROR. Default: WARN')
  parser.add_argument('inputfile', type=str, nargs=1, help="Input file name. Expects a raw file with signed 16-bit samples in platform default byte order. Use '-' to read from stdin. Example: rtl_fm -M -f 868.35M -s 160k | ./decode_elv_wde1.py -")

  args = parser.parse_args()

  loglevel = args.log
  loglevel_num = getattr(logging, loglevel.upper(), None)
  if not isinstance(loglevel_num, int):
    raise ValueError('Invalid log level: ' + loglevel)
  logging.basicConfig(stream=sys.stderr, level=loglevel_num)

  dec = decoder()

  filename = args.inputfile[0]
  if filename == '-':
    filename = sys.stdin.fileno()
  fin = io.open(filename, mode="rb")
  b = fin.read(512)
  while len(b) == 512:
    values = struct.unpack('256h', b)
    for val in values:
      dec.process(val)
    b = fin.read(512)

  fin.close()

if __name__ == '__main__':
  main()
