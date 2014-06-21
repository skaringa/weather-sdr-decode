#!/usr/bin/env python

# Decoder for weather data of sensors from Mebus received with RTL SDR
# Typical usage: 
# rtl_fm -M -f 868.35M -s 160k | ./decode_mebus.py -
# Help:
# ./decode_mebus.py -h

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
# The weather sensors are manufactured by 

import sys
import io
import time
import struct
import math
import logging
import argparse

class decoder(object):
  def __init__(self, noise_level=50, jitter=20):
    self.noise_level = noise_level
    self.jitter = jitter
    self.signal_state = 0
    self.pulse_len = -1
    self.decoder_state = 'wait'
    self.sync_on = []
    self.sync_off = []
    self.data = []
    self.pulse_border = 0
    self.pulse_limit = 10000

  def reset(self):
    logging.info("WAITING...")
    self.decoder_state = 'wait'
    self.sync_on = []
    self.sync_off = []

  def repeat(self):
    logging.info("REPEATING...")
    self.decoder_state = 'repeat_1'

  def process(self, value):
    self.pulse_len += 1
    next_signal_state = 1 if value > self.noise_level else 0
    #logging.debug("sample {0}: {1} ({2})".format(self.pulse_len, value, next_signal_state))
    if self.signal_state == 0:
      if next_signal_state == 0:
        if (self.decoder_state == 'data') and (self.pulse_len > self.pulse_limit):
          # end of frame
          self.dump()
          #self.decode()
          self.repeat()
        if (self.decoder_state == 'repeat_2') and (self.pulse_len > 2 * self.pulse_limit):
          self.reset()
      else:
        self.signal_goto_on()
    elif self.signal_state == 1:
      if next_signal_state == 0:
        self.signal_goto_off()
    self.signal_state = next_signal_state

  def signal_goto_on(self):
    if self.decoder_state == 'wait':
      logging.info("SYNCING...")
      self.decoder_state = 'sync'
    else:
      self.signal_off(self.pulse_len)
    self.pulse_len = 0

  def signal_goto_off(self):
    if self.decoder_state != 'wait':
      self.signal_on(self.pulse_len)
    self.pulse_len = 0

  def signal_on(self, length):
    logging.debug(" ON: {0}".format(length))
    if self.decoder_state == 'sync':
      self.sync_on_pulse(length)
    elif self.decoder_state == 'repeat_1':
      self.decoder_state = 'repeat_2'

  def signal_off(self, length):
    logging.debug("OFF: {0}".format(length))
    if self.decoder_state == 'sync':
      self.sync_off_pulse(length)
    elif self.decoder_state == 'repeat_2':
      self.expect_repeat(self.bitval(length))
    elif self.decoder_state == 'start':
      self.expect_start(self.bitval(length))
    elif self.decoder_state == 'data':
      self.databit(self.bitval(length))

  def bitval(self, length):
    if (length > self.jitter) and (length < self.pulse_border):
      return 0
    if (length > self.pulse_border) and (length < self.pulse_limit):
      return 1
    logging.warn("off pulse too long")
    self.reset()

  def expect_start(self, value):
    if value == 1:
      self.data = []
      self.decoder_state = 'data'
      logging.info("START")
    else:
      logging.warn("Start bit is not 1")
      self.reset()

  def expect_repeat(self, value):
    if value == 0:
      self.data = []
      self.decoder_state = 'start'
      logging.info("REPEAT")
    else:
      logging.warn("Repeat bit is not 0")
      self.reset()

  def databit(self, value):
    self.data.append(value)

  def sync_on_pulse(self, length):
    if (length > self.jitter) and (length < self.pulse_limit): 
      self.sync_on.append(length)
      if len(self.sync_on) > 3:
        self.reset()
    else:
      self.reset()
  
  def sync_off_pulse(self, length):
    if (length > self.jitter) and (length < self.pulse_limit): 
      self.sync_off.append(length)
      if len(self.sync_off) == 3:
        self.verify_sync_block()
    else:
      self.reset()

  def verify_sync_block(self):
    if len(self.sync_on) != 3:
      logging.warn('number of ON/OFF pulses in sync block != 3')
      self.reset()
      return
    onl = self.sync_on[0]
    onl += self.sync_on[1]
    onl += self.sync_on[2]
    offl = self.sync_off[0]
    offl += self.sync_off[1]
    onl /= 3
    offl /= 2

    logging.debug("onl={0} offl={1}".format(onl, offl))

    for i in range(0, 3):
      if math.fabs(onl - self.sync_on[i]) > self.jitter:
        logging.warn('high jitter in sync block (ON)')
        self.reset()
        return
  
    if self.sync_off[2] < 2 * offl:
      logging.warn('last OFF in sync is too short')
      self.reset()
      return
  
    self.pulse_border = self.sync_off[2] * 1.5
    self.pulse_limit = 2 * self.pulse_border
    self.decoder_state = 'start'
    logging.info("SYNC! pulse_border={0} pulse_limit={1}".format(self.pulse_border, self.pulse_limit))

  def popbits(self, num):
    val = 0
    if len(self.data) < num:
      logging.warn("data exhausted")
      return 0
    for i in range(0, num): 
      val += self.data.pop(0) << i
    return val

  def dump(self):
    logging.info("DUMP")
    s = ''
    i = 0
    for d in self.data:
      if i%4 == 0:
        s += ' '
      s += str(d)
      i += 1
    print s 

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
  parser = argparse.ArgumentParser(description='Decoder for weather data of sensors from ELV received with RTL SDR')
  parser.add_argument('--log', type=str, default='WARN', help='Log level: DEBUG|INFO|WARN|ERROR. Default: WARN')
  parser.add_argument('--noise', type=int, default='50', help='Signal level to distinguish noise from signal. Default: 50')
  parser.add_argument('inputfile', type=str, nargs=1, help="Input file name. Expects a raw file with signed 16-bit samples in platform default byte order. Use '-' to read from stdin. Example: rtl_fm -M -f 868.35M -s 160k | ./decode_elv_wde1.py -")

  args = parser.parse_args()

  loglevel = args.log
  loglevel_num = getattr(logging, loglevel.upper(), None)
  if not isinstance(loglevel_num, int):
    raise ValueError('Invalid log level: ' + loglevel)
  logging.basicConfig(stream=sys.stderr, level=loglevel_num)

  noiselevel = args.noise
  if noiselevel <= 0:
    raise ValueError('Noise must be a positive integer value')

  dec = decoder(noiselevel)

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
