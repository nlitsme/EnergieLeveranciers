from collections import defaultdict
from datetime import datetime
import re
import json

# note: 'twoyears.dat'  is the output of eneco.py
#   the 'InclVat' properties always use the current price,
#   not the price at the time of the measurement.

# 'ninemonths.txt' is a manually editted version of the twoyear type records.

#  zomer/wintertijd
# 2022-03-27T02:00:00Z   0.000000   0.000000
# 2021-03-28T02:00:00Z   0.000000   0.000000
# 2021-10-31
# 2020-10-25

# -- errors:
#   2021-08-09 00:00:00    0.00185    0.25212  : g:['EP4_012']
#   2021-08-11 00:00:00    0.00000    0.12250  : g:['EP4_012']
#   2021-11-17 19:00:00    0.00000    0.64838  : g:['F1000']
#   2021-11-17 20:00:00    0.00000    0.89038  : g:['F1000']
#   2022-03-29 00:00:00    0.01329    0.25975  : g:['EP4_012']
#   2022-03-31 00:00:00    0.20760    0.09787  : g:['EP4_012']
#   2022-06-26 00:00:00    0.01773    0.21192  : g:['EP4_012']

# -- exceptions:
#  electricity/status=NOT_MEASURED, electricity/collector=NotMeasured
#  gas/collector=Interpolated
#  gas/collector=Interpolated, electricity/collector=Interpolated
#  gas/collector=Interpolated, electricity/status=NOT_MEASURED, electricity/collector=NotMeasured
#  gas/collector=MeterInError  : g:['EP4_012'], e:None
#  gas/collector=Mixed  : g:['EP4_012'], e:None
#  gas/status=NOT_MEASURED, gas/collector=NotMeasured, electricity/status=NOT_MEASURED, electricity/collector=NotMeasured

def get(d, *path):
    for p in path:
        d = d.get(p)
        if not d:
            break
    return d

def readlines(fh):
    while True:
        line = fh.readline()
        if not line: break

        try:
            if line.startswith('Traceback'):
                break
            if line.startswith('auth:'):
                continue
            if line.startswith(' factor'):
                continue
            # input is either in python, or json.
            if re.search(r': (?:None|True|False)', line):
                # convert python dict to json
                line = re.sub(r'\'', '"', line)
                line = re.sub(r': (True|False)', lambda m:': %s' % m[1].lower(), line)
                line = re.sub(r': None', ': null', line)
            yield json.loads(line)
        except json.decoder.JSONDecodeError:
            pass

def getdata(lines):
    for l in lines:
        if usages := get(l, 'data', 'usages'):
            for usage in usages:
                for e in get(usage, 'entries'):
                    yield get(e, 'actual')
        else:
            yield l

def fixdate(d):
    if len(d)==10:
        return d+"T00:00:00"
    elif len(d)==19:
        return d
    elif len(d)==20:
        return d[:-1]

def cvdate(d):
    return datetime.fromisoformat(fixdate(d))

def enecojaar(t):
    # Dit zijn de datums waarop mijn eneco contract van tarief wisselt.
    datums = ["2013-03-16", "2014-03-11", "2015-03-29", "2016-03-29", "2017-03-22", "2018-03-22", "2019-03-24", "2020-03-24", "2021-03-24", "2022-03-24" ]

    if t<datums[0]:
        return "2012"
    for a, b in zip(datums, datums[1:]):
        if a <= t < b:
            return a[:4]
    return "2022"

def checkmeasurement(m, dbl):
    if not m:
        return False
    if m.get('status') != 'MEASURED':
        return False
    if not (m.get('isDoubleTariff') == m.get('isDoubleMeter') == dbl):
        return False
    if m.get('collectorType') != 'P4':
        return False
    return True

def check(d):
    for _ in ('warmth', 'redelivery', 'produced', 'tapWater'):
        if d.get(_):
            return False
    return checkmeasurement(d.get('gas'), False) and checkmeasurement(d.get('electricity'), True)

def measurementdeviations(which, m, dbl):
    l = []
    if m.get('status') != 'MEASURED':
        l.append(f"{which}/status={m.get('status')}")
    if not (m.get('isDoubleTariff') == m.get('isDoubleMeter') == dbl):
        l.append(f"{which}/(d:{dbl}, t:{m.get('isDoubleTariff')}, m:{m.get('isDoubleMeter')})")
    if m.get('collectorType') != 'P4':
        l.append(f"{which}/collector={m.get('collectorType')}")
    return l


def deviations(d):
    l = []
    for typ in ('warmth', 'redelivery', 'produced', 'tapWater', 'gas', 'electricity'):
        if v := d.get(typ):
            l.append(f"{typ}={v}")
            l += measurementdeviations(typ, v, dbl=(typ!='gas'))

    return ", ".join(l)


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Eneco per hour info')
    parser.add_argument('--verbose', '-v', action='store_true')
    parser.add_argument('--perday', '-d', action='store_true')
    parser.add_argument('--perweek', '-w', action='store_true')
    parser.add_argument('--permonth', '-m', action='store_true')
    parser.add_argument('--peryear', '-y', action='store_true')
    parser.add_argument('--eneco', '-e', action='store_true')
    parser.add_argument('--columns', action='store_true')
    parser.add_argument('--full', action='store_true', help='print full float values')
    parser.add_argument('filename', type=str)
    args = parser.parse_args()

    per = defaultdict(lambda:defaultdict(float))
    times = set()

    done = set()
    with open(args.filename, "r") as fh:
        for d in getdata(readlines(fh)):
            isok = check(d)
            t = cvdate(get(d, 'date'))
            if t in done:
                continue
            done.add(t)
            values = dict()
            errors = dict()
            for typ in ('warmth', 'redelivery', 'produced', 'tapWater', 'gas', 'electricity'):
                if v := get(d, typ, 'high') or get(d, typ, 'low'):
                    values[typ] = v
                if v := get(d, typ, 'errorCodes'):
                    errors[typ] = v

            if args.perday:
                tsum = f"{t:%Y-%m-%d}"
            elif args.perweek:
                tsum = f"{t:%Y:%W}"
            elif args.permonth:
                tsum = f"{t:%Y-%m}"
            elif args.peryear:
                tsum = f"{t:%Y}"
            elif args.eneco:
                tsum = f"{t:%Y-%m-%d}"
                tsum = enecojaar(tsum)
            else:
                tsum = f"{t:%Y-%m-%d %H}"
                if args.verbose:
                    if not isok or errors:
                        print(f"{t:%Y-%m-%d %H:%M:%S}", end="")
                        for typ, v in sorted(values.items()):
                            print(f"  {typ[:1]}:{v:7.4f}", end="")
                    if not isok:
                        print("*", end="")
                        print(deviations(d), end="")
                    if errors:
                        print(f"  : {errors}")
                    elif not isok:
                        print()

            if tsum:
                times.add(tsum)
                for typ, v in values.items():
                    per[typ][tsum] += v

    if args.columns:
        for typ, table in sorted(per.items()):
            dates = set(k[:10] for k in table.keys())
            print("--")
            print("       ", end="")
            for d in sorted(dates):
                print("%8s" % d[5:], end=" ")
            print()
            for h in range(24):
                print(f"{h:02d}:00  ", end="")
                for d in sorted(dates):
                    print("%8.3f" % table[f"{d} {h:02d}"], end=" ")
                print()
    else:
        for t in sorted(times):
            print(f"{t}", end="")
            for typ, v in sorted(per.items()):
                if args.full:
                    print(f"  {typ[:1]}:{v[t]:>22}", end="")
                else:
                    print(f"  {typ[:1]}:{v[t]:7.4f}", end="")
            print()

if __name__=='__main__':
    main()

