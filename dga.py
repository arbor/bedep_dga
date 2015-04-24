import urllib2
import xml.etree.ElementTree as ET
import struct
import json
import random
from decimal import Decimal
from datetime import datetime

class BedepDGA:

    def __init__(self, config):
        self.config = config

        self.utctime_xml = "http://www.earthtools.org/timezone/0/0"
        self.currency_xml = "http://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml"

        self.max_currencies = self.config["max_currencies"]

        # table extracted from dll
        fp = open(self.config["table"], "rb")
        self.transform2_table = json.loads(fp.read())
        fp.close()

        # main "struct"
        self.main = {}

        # affected by transform1
        self.main["num_domains"] = None # field_0
        self.main["field_4"] = None # generated seed
        self.main["field_8"] = None # part of generated seed
        self.main["field_c"] = None # part of generated seed

        self.main["min_domain_len"] = 0xc # field_10, constant
        self.main["field_14"] = 0x12 # constant, part of domain len modulus
        self.main["field_18"] = 0x16 # constant, part of generated seed
        self.main["field_1c"] = 0x1c # constant, part of generated seed
        self.main["tld"] = ".com" # field_20
        self.main["field_28"] = self.config["value1"]
        self.main["days_since"] = None # field_30, calculated from xml


    def download_currency_xml(self):
        request = urllib2.urlopen(self.currency_xml)
        xml = request.read()

        print "\tdownloaded currency xml, %d bytes" % len(xml)

        return xml


    def get_currency_xml_dates(self, xml):
        dates = []

        root = ET.fromstring(xml)
        cube1 = root.find("{http://www.ecb.int/vocabulary/2002-08-01/eurofxref}Cube")
        cube2s = cube1.findall("{http://www.ecb.int/vocabulary/2002-08-01/eurofxref}Cube")
        for cube2 in cube2s:
            dates.append(cube2.get("time"))

        print "\tparsed %d dates from currency xml" % len(dates)
        print "\tfirst date: %s" % dates[0]
        
        return dates


    def get_days_since(self, year, month, day):
        # days since year 0, 0000-00-00
        # off by a month
        v4 = year % 400 
        v5 = 146097 * (year / 400) + day + 365 * (year % 400) + ((year % 400 + 3) >> 2)

        if v4 > 100:
            v5 -= 1
            if v4 > 200:
                v5 -= 1
                if v4 > 300:
                    v5 -= 1

        v6 = 31 * month + v5

        if month >= 8:
            month -= 1

        result = v6 - (month >> 1)

        if month > 1:
            result -= 1
            if v4: 
                if v4 & 3 or v4 == 100 or v4 == 200 or v4 == 300:
                    result -= 1

        return result


    def get_three_days_ago(self):
        # days since "three days ago per utctime_xml"
        request = urllib2.urlopen(self.utctime_xml)
        xml = request.read()

        root = ET.fromstring(xml)

        utctime = root.findall("utctime")[0].text
        dt = datetime.strptime(utctime, "%Y-%m-%d %H:%M:%S")

        # month and day are decremented by 1 for this algorithm
        days_since = self.get_days_since(dt.year, dt.month-1, dt.day-1)
        milliseconds_since = 3600000 * dt.hour + 86400000 * days_since + 60000 * dt.minute + 1000 * dt.second
        three_days_ago = (milliseconds_since - 172800000) / 86400000
        
        print "\tthree days ago: 0x%x (%d)" % (three_days_ago, three_days_ago)

        return three_days_ago


    def get_currencies(self, xml, date):
        currencies = []

        root = ET.fromstring(xml)
        cube1 = root.find("{http://www.ecb.int/vocabulary/2002-08-01/eurofxref}Cube")
        cube2s = cube1.findall("{http://www.ecb.int/vocabulary/2002-08-01/eurofxref}Cube")
        for cube2 in cube2s:
            if cube2.get("time") == date:
                for cube3 in cube2:
                    if len(currencies) == self.max_currencies:
                        print "\thit max currencies (%d)" % len(currencies)
                        break

                    currency = self.parse_currency(cube3.get("currency"), cube3.get("rate"))
                    currencies.append(currency)

                break

        print "\tparsed %d currencies from %s (currency date):" % (len(currencies), date)
        for currency in currencies:
            print "\t\t%s: %s" % (currency["name"], currency["rate_str"])

        return currencies


    def parse_currency(self, name, rate):
        currency = {}

        currency["name"] = name
        currency["name_bin"] = struct.unpack("I", name+"\x00")[0]

        currency["rate_str"] = rate

        currency["real_rate_float"] = self.broken_float(rate)
        currency["real_rate"] = struct.unpack("q", struct.pack("d", currency["real_rate_float"]))[0]
        currency["real_rate_low"], currency["real_rate_high"] = struct.unpack("II", struct.pack("d", currency["real_rate_float"]))

        # for debugging
        currency["real_rate_hex"] = "0x%x" % struct.unpack("q", struct.pack("d", currency["real_rate_float"]))[0]

        return currency


    def broken_float(self, str_float):
        # bedep's atof()
        # off by a bit
        one, two = str_float.split(".")
        num_digits = len(str(two))

        one = int(one)
        two = int(two)
        v10 = 10
        v11 = 0 

        while True:
            if num_digits <= 1:
                break

            if num_digits & 1:
                if v11:
                    v11 *= v10 
                else:
                    v11 = v10 

            num_digits >>= 1
            v10 *= v10 

        if v11:
            v10 *= v11 

        result = Decimal((float(two)/float(v10))+float(one))

        return result


    def transform1(self, currencies):
        math1 = (self.main["field_18"] + (self.main["field_28"] ^ self.main["days_since"])) & 0xffffffff
        math2 = ((self.main["days_since"] ^ currencies[0]["real_rate_low"]) + (self.main["field_1c"] ^ currencies[0]["name_bin"])) & 0xffffffff

        for i in range(len(currencies), 0, -1):
            math1 = (self.main["field_28"] ^ (math2 + 0x1a43ba27 * math1)) & 0xffffffff

        math4, ret1, ret2 = self.transform2(math1)
        self.transform7(math4, ret1, ret2)

        return 


    def transform7(self, a1, a2, a3):
        self.main["num_domains"] = a3 - 1
        print "\t\t%d domains" % self.main["num_domains"]

        v1, v9 = self.transform8(a1, a2, a3)

        v5 = (self.transform9() % (a3 - 1)) + 1
        v6 = self.transform9() % (v1 + 1)

        self.main["field_c"] = a1 

        self.main["field_4"] = pow(v9[0], v5, a1)

        v8 = v9[1]
        if ((v6 - 1) & 0x80000000) == 0:
            v8 = pow(v9[1], v9[2:][v6 - 1], a3)


        self.main["field_8"] = v8

        return


    def transform9(self):
        # transform is seeded by rdtsc
        # only lower 32-bits are used
        # effectively returns a random 32-bit number
        return random.getrandbits(32)

        # XXX code
        # v0 = rdtsc
        #v0_lo = 0x3c4017a4
        #v0_hi = 0x3747
        # qword = 0x84d4693e80311888 (hardcoded)
        #v1 = ((qword + 0x18ee4a7a * v0_lo) ^ 0xd29adc50) & 0xffffffff
        #v2 = ((((self & 0xffffffff00000000) >> 32) + 0x2feea1ae * v0_hi) ^ 0x8dc850c) & 0xffffffff
        #qword = v1 + self.ntdll_aullmul(v2, 0, 0, 1)
        #qword = 0x1c63278cca9318e0
        #return (v2 + 8831 * v1) & 0xffffffff


    def transform8(self, a1, a3, a4):
        a2 = []

        trans4 = pow(a3, ((a1 - 1) / a4), a1)

        a2.append(trans4)

        v4 = a4  - 1
        v5 = 3
        v6 = 0

        v18 = []

        i = 0x25
        while True:
            v7 = 0

            if v5 >= v4:
                break

            v20 = v6 - 1
            if v6 < 1:
                i -= 1
                if (i & 0x80000000) != 0:
                    break
                v18.append(v5)
                v6 += 1
            else:
                while True:
                    v8 = v5 % v18[v7]
                    v7 += 1

                    if not v8:
                        break

                    v20 -= 1
                    if v20 < 0:
                        i -= 1
                        if (i & 0x80000000) != 0:
                            break
                        v18.append(v5)
                        v6 += 1
                        break
            v5 += 2

        v21 = 0
        v9 = 0
        v10 = 0

        while (v6 - 1) >= 0:
            v6 -= 1

            i = v18[v9]
            if not (v4 % i):
                if v9 != v10:
                    v18[v10] = i
                v10 += 1
                v21 += 1
            v9 += 1

        v11 = self.transform3(a4, v21, v18)

        i = 0
        if v11:
            v12 = 3
            a2.append(v11)
            
            if a4 > 3:
                while True:
                    if v12 >= a4:
                        break

                    v15 = 0
                    while True:
                        v16 = v12 % v18[v15]
                        v15 += 1

                        if not v16:
                            break

                        v21 -= 1
                        if v21 <= 0:
                            i += 1
                            a2.append(v12)
                            break
                    v12 += 2

        return (i, a2)


    def transform2(self, a1):
        # XXX
        # this transform uses an external table extracted from the dll
        # i don't know what table data is or how it's formatted
        # so this is a best effort implmentation based on the code and trial and error runs
        #
        # likely something fermat number related
        x = 0
        v20 = []
        for i in range(102):
            table_entry = self.transform2_table[i]
            
            two_idx = [i, 2]
            two = self.transform2_table[two_idx[0]][two_idx[1]]

            math2 = (0x281 * table_entry[1] ^ self.config["value2"]) & 0xffffffff

            for j in range(math2, 0, -1):
                math3 = ((0x663d81 * two ^ self.config["value2"]) - i) & 0xffffffff

                # sometimes a table entry spills over to the next entry
                two_idx[1] += 1
                if two_idx[1] == len(table_entry):
                    two_idx[0] += 1
                    two_idx[1] = 0

                two = self.transform2_table[two_idx[0]][two_idx[1]]

                if (math3 - 1) >= self.main["field_18"] and (math3 - 1) <= self.main["field_1c"]:
                    if x >= 0xa8:
                        break

                    x += 1
                    v20.append(i)
                    v20.append(math3)

        table_idx = v20[(a1 % x) * 2]
        table_entry = self.transform2_table[table_idx]

        math4 = (0x663d81 * table_entry[0] ^ self.config["value3"]) & 0xffffffff
        math5 = (0x281 * table_entry[1] ^ self.config["value2"]) & 0xffffffff
        two_idx = [table_idx, 2]
        two = self.transform2_table[two_idx[0]][two_idx[1]]

        v22 = []
        for i in range(math5):
            v22.append(((0x663d81 * two ^ self.config["value2"]) - table_idx) & 0xffffffff)

            two_idx[1] += 1
            if two_idx[1] == len(table_entry):
                two_idx[0] += 1
                two_idx[1] = 0
            two = self.transform2_table[two_idx[0]][two_idx[1]]

        ret1 = []
        v17 = self.transform3(math4, math5, v22)
        ret2 = v20[((a1 % x) * 2) + 1]

        return (math4, v17, ret2)


    def transform3(self, a1, a2, a3):
        v3 = 2
        if (a1 >> 1) >= 2:
            while True:
                i = pow(v3, ((a1 - 1) >> 1), a1)

                a3_idx = 0
                while True:
                    if i == 1:
                        break

                    a2 -= 1
                    if a2 < 0:
                        return v3
                    v5 = a3[a3_idx]
                    a3_idx += 1

                    i = pow(v3, (a1 - 1) / v5, a1)


                v3 += 1
                if v3 <= (a1 >> 1):
                    continue
                break

        return 0


    def run(self):
        # field_38 of "xml" struct
        three_days_ago = self.get_three_days_ago()

        # field_3c of "xml" struct"
        day_of_week = 1 # monday

        currency_xml = self.download_currency_xml()
        dates = self.get_currency_xml_dates(currency_xml)

        print "\tfinding correct days since:"
        for date in dates:
            dt = datetime.strptime(date, "%Y-%m-%d")
            
            # month and day of "date"  are decremented by 1 for days_since algorithm
            # returned days_since will be "date" minus 1
            days_since = self.get_days_since(dt.year, dt.month-1, dt.day-1)
            print "\t\ttrying: 0x%x (%d)" % (days_since, days_since),

            # at least 3 days ago and is on day_of_week
            if days_since <= three_days_ago and (days_since + 5) % 7 == day_of_week:
                print "found"
                break
            else:
                print "nope"

        self.main["days_since"] = days_since

        # currency date will be "date"
        currencies = self.get_currencies(currency_xml, date)

        print "\trunning transforms"
        self.transform1(currencies)
        
        domains = []
        for i in range(self.main["num_domains"]):
            domain = self.transform10(currencies)
            domains.append(domain)

        print "\ttransforms done"
        print
        return domains
           

    def transform10(self, currencies):
        self.main["field_4"] = pow(self.main["field_4"], self.main["field_8"], self.main["field_c"])


        print "\t\tseed: 0x%x" % self.main["field_4"]

        domain = self.transform11(currencies, self.main["field_4"])

        return domain


    def transform11(self, currencies, a1):
        domain = []
        currency = currencies[0]

        math1 = self.main["field_14"] * self.main["days_since"]
        math2 = ((self.main["field_28"] ^ currency["name_bin"]) - (currency["real_rate"] >> 0x20)) & 0xffffffff

        for i in range(len(currencies)):
            math1 = ((self.main["min_domain_len"] + self.main["days_since"] * currency["real_rate_low"]) ^ (math2 + 0x19d65 * (self.main["field_28"] ^ math1))) & 0xffffffff

        math3 = 0x283 * self.main["days_since"]

        # calculate domain len
        math4 = (self.main["min_domain_len"] + (a1 ^ math1) % (self.main["field_14"] - self.main["min_domain_len"] + 1)) & 0xffffffff
        domain_len = math4 - 1

        while True:
            print "\t\t\tmixing in %s's rate" % currency["name"]
            if domain_len < 0:
                break

            # generate domain chr
            math6 = (0x6e93d938959d4fd8 * (self.main["field_28"] + self.main["min_domain_len"] * currency["name_bin"])) & 0xffffffffffffffff
            math7 = (0x17a87709884ed9f3 * (self.main["field_14"] + currency["real_rate"]) + math6) & 0xffffffffffffffff

            v16 = 0x1a
            if domain_len <= 1:
                v16 = 0x24 

            domain_chr = ((math3 ^ ((math7 >> 17) - a1)) & 0xffffffff) % v16 + ord("a")
            if domain_chr > 0x7a:
                domain_chr = ((math3 ^ ((math7 >> 17) - a1)) & 0xffffffff) % v16 + 0x16

            print "\t\t\tdomain chr: %s" % chr(domain_chr)
            domain.append(chr(domain_chr))

            currency = self.get_next_currency(currencies, math1, currency)
            a1 = (domain_len ^ self.ror(a1, 7, 32)) & 0xffffffff
            domain_len -= 1
        
        domain = "".join(domain) + self.main["tld"]
        print "\t\t\tdomain: %s" % domain

        return domain


    def get_next_currency(self, currencies, offset, prev_currency):
        index = 0
        for currency in currencies:
            if currency["name"] == prev_currency["name"]:
                break
            index += 1

        index = (index + offset) % len(currencies)

        return currencies[index]


    def ror(self, num, count, size):
        return ((num >> count) | (num << (size-count)))


if __name__ == "__main__":

    configs = [
            # AML-18141460
            {
                "value1": 0x9be6851a,
                "value2": 0xd666e1f3,
                "value3": 0x2666ca48,
                "table": "transform2_table_var1.json",
                "max_currencies": 48,
            },

            # AML-19646835
            {
                "value1": 0x36a64c8a,
                "value2": 0x7cd02d69,
                "value3": 0x8cd006d2,
                "table": "transform2_table_var2.json",
                "max_currencies": 48,
            },
            # AML-20382547
            {
                "value1": 0x4cdff15c,
                "value2": 0x1bbae2d4,
                "value3": 0xebbac96f,
                "table": "transform2_table_var3.json",
                "max_currencies": 36,
            },
        ]

    for i, config in enumerate(configs):
        print "config%d" % i

        dga = BedepDGA(config)
        domains = dga.run()

        print "\t%d domains:" % len(domains)
        for domain in domains:
            print "\t\t%s" % domain
        print
