#!/usr/bin/env python

# Unit test for decode_elv_wde1

import io
import struct
import unittest
import sys
from os import path
sys.path.append(path.dirname(path.dirname(path.abspath(__file__))))
from decode_elv_wde1 import decoder

# Test hook: store the decoder output into an instance variable
# instead of printing it
class test_decoder(decoder):
  def print_decoder_output(self, decoder_out):
    self.decoder_out = decoder_out

# Unit test class
class test_decode_elv_wde1(unittest.TestCase):

  # Process the given file with the decoder
  def process_file(self, filename, decoder):
    fin = io.open("{0}/{1}".format(path.dirname(path.abspath(__file__)), filename), mode="rb")
    b = fin.read(512)
    while len(b) == 512:
      values = struct.unpack('256h', b)
      for val in values:
        decoder.process(val)
      b = fin.read(512)

    fin.close()
    decoder.finish()

  # Feed several real-world samples into the decoder
  # and verify the decoder output
  def test_sample_1(self):
    dec = test_decoder()
    self.process_file('rtl-weather-30k-1.raw', dec)
    self.assertEqual(dec.decoder_out['sensor_type_str'], 'Thermo/Hygro')
    self.assertEqual(dec.decoder_out['address'], 6)
    self.assertEqual(dec.decoder_out['temperature'], 20.2)
    self.assertEqual(dec.decoder_out['humidity'], 61.7)

  def test_sample_2(self):
    dec = test_decoder()
    self.process_file('rtl-weather-30k-2.raw', dec)
    self.assertEqual(dec.decoder_out['sensor_type_str'], 'Kombi')
    self.assertEqual(dec.decoder_out['address'], 1)
    self.assertEqual(dec.decoder_out['temperature'], 17.6)
    self.assertEqual(dec.decoder_out['humidity'], 54)
    self.assertEqual(dec.decoder_out['wind'], 0)
    self.assertEqual(dec.decoder_out['rain_sum'], 1634)
    self.assertEqual(dec.decoder_out['rain_detect'], False)

  def test_sample_3(self):
    dec = test_decoder()
    self.process_file('rtl-weather-30k-3.raw', dec)
    self.assertEqual(dec.decoder_out['sensor_type_str'], 'Thermo/Hygro')
    self.assertEqual(dec.decoder_out['address'], 4)
    self.assertEqual(dec.decoder_out['temperature'], 18.8)
    self.assertEqual(dec.decoder_out['humidity'], 61.1)

  def test_sample_4(self):
    dec = test_decoder()
    self.process_file('rtl-weather-30k-4.raw', dec)
    self.assertEqual(dec.decoder_out['sensor_type_str'], 'Thermo/Hygro')
    self.assertEqual(dec.decoder_out['address'], 6)
    self.assertEqual(dec.decoder_out['temperature'], 20.4)
    self.assertEqual(dec.decoder_out['humidity'], 61.3)

if __name__ == '__main__':
  unittest.main()
