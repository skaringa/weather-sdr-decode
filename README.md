weather-sdr-decode
====================

Decoders for wireless weather sensor data received with RTL SDR.

Prerequisites
=============

* [rtl-sdr](http://sdr.osmocom.org/trac/wiki/rtl-sdr) 
* Python 2.7, on slow machines [PyPy](http://pypy.org) is recommended
* Wireless weather sensor

decode\_elv\_wde1.py
====================

This program decodes weather data produces by wiresless sensors from [ELV](http://www.elv.de).

It should work with the following sensors:

* Temperature sensor S 300 IA
* Temperature/Hygro sensor S 300 TH und ASH 2200
* Temperature/Hygro/Wind/Rain ("Kombi") sensor KS 200/300

I've tested it with:

* Temperature/Hygro sensor S 300 TH
* Kombi sensor KS 300-2 (Picture below) 

![Picture of KS 300](http://www.kompf.de/weather/images/20090419_003.jpg)

*Typical usage:* 

  rtl\_fm -M -f 868.35M -s 30k | ./decode\_elv\_wde1.py -

*Help:* 

  ./decode\_elv\_wde1.py -h

References
----------

* [RTL SDR](http://sdr.osmocom.org/trac/wiki/rtl-sdr)
* The weather sensors are manufactured by [ELV](http://www.elv.de/)
* Helmut Bayerlein describes the [communication protocol](http://www.dc3yc.homepage.t-online.de/protocol.htm)


decode\_mebus.py
===============

This program decodes weather data produces by wiresless sensors from _Mebus_ like this one:

![Picture of Mebus outdoor sensor](http://www.kompf.de/weather/images/mebus_outdoor.jpg)

*Typical usage:* 

  rtl\_fm -M -f 433.84M -s 30k | ./decode\_mebus.py -

*Help:* 

  ./decode\_mebus.py -h

References
----------

* [RTL SDR](http://sdr.osmocom.org/trac/wiki/rtl-sdr)
* The weather sensors are manufactured by Albert Mebus GmbH, Haan, Germany

Performance
===========

To decode in real time on machines with a slower CPU like the Raspberry Pi, the usage of [PyPy](http://pypy.org) as Python interpreter is recommended. The script decode\_elv\_wde1.py runs four times faster with PyPy. To set it as standard interpreter, change the first line of the script into

  #!/usr/bin/env pypy

License
=======

Copyright 2014 Martin Kompf

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
 
This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

