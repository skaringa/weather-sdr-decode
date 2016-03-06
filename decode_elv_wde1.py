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
    # Therefore the length of a valid bit is 36.6 samples.
    self.buf_len = 35
    self.buf = [0] * self.buf_len
    self.decoder_state = 'wait'
    self.data = []
    self.min_len = 30
    self.max_len = 40
    self.pulse_len = 0
    self.pulse_lo = 0
    self.pulse_y = 0
    self.sync_count = 0

  def process(self, value):
    y = self.signal(value)
    self.pulse_len += 1
    if y == 0:
      self.pulse_lo += 1
    if y != self.pulse_y and y != 0:
      # slope low->high
      self.pulse()
      self.pulse_len = 1
      self.pulse_lo = 0
    self.pulse_y = y
    self.buf.pop(0)
    self.buf.append(value)

  def finish(self):
    if self.decoder_state == 'data':
      self.data.append(1)
      self.decode()

  def signal(self, value):
    avr = sum(self.buf) / self.buf_len
    logging.debug("avr={0}".format(avr))
    return 0 if value < avr else 1
    
  def bitval(self):
    val = -1
    if self.pulse_len >= self.min_len and self.pulse_len <= self.max_len:
      if self.pulse_lo < self.pulse_len / 2:
        val = 0
      else:
        val = 1

    logging.debug("bitval: len={0} lo={1} val={2}".format(self.pulse_len, self.pulse_lo, val))
    return val
    
  def pulse(self):
    val = self.bitval()
    if val == -1:
      if self.decoder_state == 'data':
        # end of frame?
        self.data.append(1)
        self.decode()
        self.data = []
      self.decoder_state = 'wait'
    elif self.decoder_state == 'wait':
      if val == 0:
        # first sync pulse
        self.sync_count = 1;
        self.decoder_state = 'sync';
        logging.info("SYNC")
    elif self.decoder_state == 'sync':
      if val == 0:
        # another sync pulse
        self.sync_count += 1
      elif val == 1 and self.sync_count > 6:
        # got the start bit
        self.sync_count = 0
        self.decoder_state = 'data'
        logging.info("DATA")
    elif self.decoder_state == 'data':
      self.data.append(val)

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

    # compute values
    decoder_out = {
      'sensor_type': sensor_type,
      'sensor_type_str': sensor_types[sensor_type],
      'address': dec[0] & 7,
      'temperature': (dec[3]*10. + dec[2] + dec[1]/10.) * (-1. if dec[0]&8 else 1.),
      'humidity': 0.,
      'wind': 0.,
      'rain_sum': 0,
      'rain_detect': 0,
      'pressure': 0
    }
  
    if sensor_type == 7:
      # Kombisensor
      decoder_out['humidity'] = dec[5]*10. + dec[4]
      decoder_out['wind'] = dec[8]*10. + dec[7] + dec[6]/10.
      decoder_out['rain_sum'] = dec[11]*16*16 + dec[10]*16 + dec[9]
      decoder_out['rain_detect'] = dec[0]&2 == 1

    if (sensor_type == 1) or (sensor_type == 4):
      # Thermo/Hygro
      decoder_out['humidity'] = dec[6]*10. + dec[5] + dec[4]/10.

    if sensor_type == 4:
      # Thermo/Hygro/Baro
      decoder_out['pressure'] = 200 + dec[9]*100 + dec[8]*10 + dec[7]

    self.print_decoder_output(decoder_out)

  def print_decoder_output(self, decoder_out):
    print(time.strftime("time: %x %X"))
    print("sensor type: " + decoder_out['sensor_type_str'])
    print("address: {0}".format(decoder_out['address']))

    print("temperature: {0}".format(decoder_out['temperature']))

    if decoder_out['sensor_type'] == 7:
      # Kombisensor
      print("humidity: {0}".format(decoder_out['humidity']))
      print("wind: {0}".format(decoder_out['wind']))
      print("rain sum: {0}".format(decoder_out['rain_sum']))
      print("rain detector: {0}".format(decoder_out['rain_detect']))
    if (decoder_out['sensor_type'] == 1) or (decoder_out['sensor_type'] == 4):
      # Thermo/Hygro
      print("humidity: {0}".format(decoder_out['humidity']))
    if decoder_out['sensor_type'] == 4:
      # Thermo/Hygro/Baro
      print("pressure: {0}".format(decoder_out['pressure']))

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
  dec.finish()

if __name__ == '__main__':
  main()
