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
    else:
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
    for _ in ('warmth', 'redelivery', 'produced', 'tapWater'):
        if d.get(_):
            l.append(f"warmth={d.get(_)}")

    l += measurementdeviations('gas', d.get('gas'), False)
    l += measurementdeviations('electricity', d.get('electricity'), True)

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
    parser.add_argument('filename', type=str)
    args = parser.parse_args()

    e_per = defaultdict(float)
    g_per = defaultdict(float)

    with open(args.filename, "r") as fh:
        for d in getdata(readlines(fh)):
            isok = check(d)
            t = cvdate(get(d, 'date'))
            g = get(d, 'gas', 'high')
            e = get(d, 'electricity', 'high') or get(d, 'electricity', 'low')
            g_err = get(d, 'gas', 'errorCodes')
            e_err = get(d, 'electricity', 'errorCodes')

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
                    if not isok or g_err or e_err:
                        print(f"{t:%Y-%m-%d %H:%M:%S} {g:>10.5f} {e:>10.5f}", end="")
                    if not isok:
                        print("*", end="")
                        print(deviations(d), end="")
                    if g_err or e_err:
                        print(f"  : g:{g_err}, e:{e_err}")
                    elif not isok:
                        print()

            if tsum:
                e_per[tsum] += e
                g_per[tsum] += g

    if args.columns:
        for table in (g_per, e_per):
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
        for t in sorted(e_per.keys()):
            print("%s %10.5f %10.5f" % (t, g_per[t], e_per[t]))

if __name__=='__main__':
    main()

