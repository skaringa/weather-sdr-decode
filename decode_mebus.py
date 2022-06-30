#!/usr/bin/env python

# Decoder for weather data of sensors from Mebus received with RTL SDR
# Typical usage: 
# rtl_fm -M am -f 433.84M -s 30k | ./decode_mebus.py -
# Help:
# ./decode_mebus.py -h

# Copyright 2014,2022 Martin Kompf
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
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

# References:
# RTL SDR <https://osmocom.org/projects/rtl-sdr/wiki/Rtl-sdr>
# The weather sensors are manufactured by Albert Mebus GmbH, Haan, Germany

import sys
import io
import time
import struct
import math
import logging
import argparse

class decoder(object):
  def __init__(self):
    # Because we are sampling at 30khz (33.3us),
    # the length of the sync block is about 90 samples.
    self.buf = [0] * 90
    self.decoder_state = 'wait'
    self.pulse_len = 0
    self.clipped = 0
    self.noise_level = 0
    self.signal_state = 0
    self.data = []
    self.frames = []
    self.pulse_border = 88 # distinguish between logical 0 and 1
    self.pulse_limit = 177 # to determine the end of a packet

  def reset(self):
    logging.info("WAITING...")
    self.decoder_state = 'wait'
    self.frames = []
    self.pulse_len = 0

  def repeat(self):
    logging.info("REPEATING...")
    self.frames.append(self.data)
    self.decoder_state = 'repeat_1'

  def process(self, value):
    self.buf.pop(0)
    self.buf.append(value)
    self.pulse_len += 1

    if self.clipped % 10000 == 1:
      logging.error("Clipped signal detected, you should reduce gain of receiver!")

    if self.decoder_state == 'wait': 
      if self.pulse_len > 90:
        self.test_sync_block()
      return

    # at this point we have a valid sync block and know the noise_level
    # to detect pulses
    next_signal_state = 1 if value > self.noise_level else 0
    if self.signal_state == 0:
      if next_signal_state == 0:
        if (self.decoder_state == 'data') and (self.pulse_len > self.pulse_limit):
          # end of frame
          self.dump()
          self.repeat()
        if (self.decoder_state == 'repeat_2') and (self.pulse_len > 2 * self.pulse_limit):
          # End of packet
          self.decode()
          self.reset()
      else:
        self.signal_goto_on()
    elif self.signal_state == 1:
      if next_signal_state == 0:
        self.signal_goto_off()
    self.signal_state = next_signal_state

  def test_sync_block(self):
    # A valid sync block has the levels on-off-on-off-on-off.
    # Each level has a duration of avr. 15 samples. 
    # But allow a jitter of 5 samples for each level change.
    avh0 = self.signal_avr(0, 10)
    avl0 = self.signal_avr(20, 25)
    if avh0 < avl0 * 2:
      return # high signal ampl. should be greater than low

    rgh0 = self.signal_range(0, 10)
    rgl0 = self.signal_range(20, 25)
    if avh0 < rgh0 or avh0 < rgl0:
      return # average of high signal amplitude should be greater than noise

    avh1 = self.signal_avr(35, 40)
    avl1 = self.signal_avr(50, 55)
    if avh1 < avl1 * 2:
      return # high signal ampl. of second pulse should be greater than low

    if avh1 < avl0 or avh0 < avl1:
      return # high of second pluse should be greate than low of first

    avh2 = self.signal_avr(65, 70)
    avl2 = self.signal_avr(80, 90)
    if avh2 < avl2 * 2:
      return # high signal ampl. of third pulse should be greater than low

    if avh2 < avl0 or avh0 < avl2:
      return # high of third pluse should be greater than low of first

    # Valid sync block found!
    self.decoder_state = 'sync'
    self.signal_state = 0
    self.noise_level = (avh0 + avl0 + avh1 + avl1 + avh2 + avl2) / 6
    self.pulse_len = 0
    logging.info("SYNC!")
    logging.debug("noise_level={0}".format(self.noise_level))

  def signal_avr(self, begin, end):
    sm = sum(self.buf[begin:end])
    return sm/(end-begin) 

  def signal_range(self, begin, end):
    mn = min(self.buf[begin:end])
    mx = max(self.buf[begin:end])
    if mx > 32500 or mn < -32500:
      self.clipped += 1 
    return mx-mn

  def signal_goto_on(self):
    self.signal_off(self.pulse_len)
    self.pulse_len = 0

  def signal_goto_off(self):
    self.signal_on(self.pulse_len)
    self.pulse_len = 0

  def signal_on(self, length):
    logging.debug(" ON: {0}".format(length))
    if self.decoder_state == 'sync':
      self.decoder_state = 'start'
    if self.decoder_state == 'repeat_1':
      self.decoder_state = 'repeat_2'

  def signal_off(self, length):
    logging.debug("OFF: {0}".format(length))
    if self.decoder_state == 'repeat_2':
      self.expect_repeat(self.bitval(length))
    elif self.decoder_state == 'start':
      self.expect_start(self.bitval(length))
    elif self.decoder_state == 'data':
      self.data.append(self.bitval(length))

  def bitval(self, length):
    if length < self.pulse_border:
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

  def popbits(self, num):
    val = 0
    if len(self.data) < num:
      logging.warn("data exhausted")
      return 0
    for i in range(0, num): 
      val <<= 1
      val += self.data.pop(0)
    return val

  def dump(self):
    logging.info("DUMP Frame")
    s = ''
    i = 0
    for d in self.data:
      if i%4 == 0:
        s += ' '
      s += str(d)
      i += 1
    logging.info(s) 

  def decode(self):
    logging.info("DECODE")
    if len(self.frames) == 0:
      logging.warn("Frame contains no data")
      self.reset()
      return

    # check if all frames contain the same data
    check = self.frames[0]
    for i in range(1, len(self.frames)):
      if check != self.frames[i]:
        logging.warn("Frame {0} is not equals to first one".format(i))
        self.reset()
        return

    id = self.popbits(11)
    setkey = self.popbits(1)
    channel = self.popbits(2)
    temp = self.popbits(12) 
    if temp >= 2048:
      # negative value
      temp = temp - 4096
    hum = self.popbits(8)

    print(time.strftime("time: %x %X"))
    print("id: {0}".format(id))
    print("setkey: {0}".format(setkey))
    print("channel: {0}".format(channel + 1))
    print("temperature: {0}".format(temp/10.0))
    print("humidity: {0}".format(hum))

    print
      
def main():
  parser = argparse.ArgumentParser(description='Decoder for weather data of sensors from Mebus received with RTL SDR')
  parser.add_argument('--log', type=str, default='WARN', help='Log level: DEBUG|INFO|WARN|ERROR. Default: WARN')
  parser.add_argument('inputfile', type=str, nargs=1, help="Input file name. Expects a raw file with signed 16-bit samples in platform default byte order and 30 kHz sample rate. Use '-' to read from stdin. Example: rtl_fm -M am -f 433.84M -s 30k | ./decode_mebus.py -")

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
