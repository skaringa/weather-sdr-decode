#!/usr/bin/env python

# Decoder for weather data of sensors from ELV received with RTL SDR
# Typical usage: 
# rtl_fm -M -f 868.35M -s 30k | ./decode_elv_wde1.py -
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
    # We are sampling at 30khz (33.3us),
    # and the length of a bit is always 1220us.
    # Therefore the length of the buffer fo a whole bit is 36.6 samples.
    # Round this down to 35 avoid getting the next bit into the buffer
    self.buf = [0] * 35
    self.decoder_state = 'wait'
    self.pulse_len = 0
    self.on_level = 0
    self.sync_count = 0
    self.data = []
    self.clipped = 0

  def process(self, value):
    x = self.buf.pop(0);
    self.buf.append(value);
    self.pulse_len += 1
    if self.pulse_len <= 35:
      return # buffer not filled

    if self.clipped % 10000 == 1:
      logging.error("Clipped signal detected, you should reduce gain of receiver!")

    if self.decoder_state == 'wait':
      self.sync_count = 0
      self.data = []
      self.test_sync0() # search for first sync bit
    else:
      val = self.bitval()
      logging.debug("bitval = {0}".format(val))
      if val == -1:
        # Failed to decode bitval
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
        elif val == 1 and self.sync_count > 6:
          # got the start bit
          logging.info('DATA')
          self.decoder_state = 'data'
      elif self.decoder_state == 'data':
        self.data.append(val)

  def test_sync0(self):
    # Test if the data in the buffer is the first sync bit
    # This bit consists of high amplitude with ~21 samples
    # and low amplitude with ~10 samples
    
    avh = self.signal_avr(0, 20)
    avl = self.signal_avr(26, 33)
    if avh < avl * 2:
      return # high signal ampl. should be greater than low

    rgh = self.signal_range(0, 20)
    rgl = self.signal_range(26, 33)
    if avh < rgh or avh < rgl:
      return # average of high signal amplitude should be greater than noise
    
    # We found a valid sync 0
    self.decoder_state = 'sync'
    self.on_level = (avh+avl)/2
    self.pulse_len = 0
    logging.info("SYNC!")
    logging.debug("avh={0} avl={1}".format(avh, avl))
    return
  
  def signal_avr(self, begin, end):
    sm = sum(self.buf[begin:end])
    return sm/(end-begin) 

  def signal_range(self, begin, end):
    mn = min(self.buf[begin:end])
    mx = max(self.buf[begin:end])
    if mx > 32500 or mn < -32500:
      self.clipped += 1 
    return mx-mn

  def bitval(self):
    # detect start of bit: the signal shouldnow be at off level, 
    # so detect a transition to on
    skip = 0
    while skip < 4:
      x = self.buf[skip]
      if x > self.on_level:
        break
      skip += 1

    self.pulse_len = -skip
    logging.debug("skip={0}".format(skip))
    if skip >= 4:
      logging.debug("No starting slope off->on deteced")
      return -10 

    # first 12 samples always high signal
    # but allow a jitter of 1 sample
    val = -1
    aa = self.signal_avr(skip, skip+10);
    # Next 12 samples either low or high depending on bitval 
    ma = self.signal_avr(skip+13, skip+22)
    # last 12 samples should be always low signal
    ea = self.signal_avr(skip+25, 33)

    if aa > ea:
      if abs(ma-aa) > abs(ma-ea):
        val = 1
      else:
        val = 0 

    self.on_level = (aa+ea)/2
    logging.debug("bitval: a={0} m={1} e={2} val={3}".format(aa, ma, ea, val))
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
  parser.add_argument('inputfile', type=str, nargs=1, help="Input file name. Expects a raw file with signed 16-bit samples in platform default byte order and 30 kHz sample rate. Use '-' to read from stdin. Example: rtl_fm -M -f 868.35M -s 30k | ./decode_elv_wde1.py -")

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
