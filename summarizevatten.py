from collections import defaultdict
from datetime import datetime
import re
import json

def get(d, *path):
    for p in path:
        d = d.get(p)
        if not d:
            break
    return d

def readlines(fh):
    """
    reads lines containing either python or json dicts
    """
    while True:
        line = fh.readline()
        if not line: break

        try:
            # input is either in python, or json.
            if re.search(r': (?:None|True|False)', line):
                # convert python dict to json
                line = re.sub(r'\'', '"', line)
                line = re.sub(r': (True|False)', lambda m:': %s' % m[1].lower(), line)
                line = re.sub(r': None', ': null', line)
            yield json.loads(line)
        except json.decoder.JSONDecodeError:
            pass

def mkdate(ymd, hm):
    return datetime.fromisoformat(f"{ymd}T{hm}:00")

def getdata(lines):
    for l in lines:
        for cc in get(l, 'ConsumptionHeaderSet'):
            product = get(cc, 'Product')
            for c in get(cc, 'ConsumptionSet'):
                t = mkdate(get(c, 'DateFrom'), get(c, 'TimeFrom') or '00:00')
                q = float(get(c, "DeliveryQuantity"))
                qr = float(get(c, "BackDeliveryQuantity"))
                yield (product, t, q, qr)
 
def main():
    import argparse
    parser = argparse.ArgumentParser(description='Vattenfall gas, elec per hour info')
    parser.add_argument('--verbose', '-v', action='store_true')
    parser.add_argument('--perday', '-d', action='store_true')
    parser.add_argument('--perweek', '-w', action='store_true')
    parser.add_argument('--permonth', '-m', action='store_true')
    parser.add_argument('--peryear', '-y', action='store_true')
    parser.add_argument('--columns', action='store_true')
    parser.add_argument('filename', type=str)
    args = parser.parse_args()

    e_per = defaultdict(float)
    e_rcvd = defaultdict(float)
    e_xmit = defaultdict(float)
    g_per = defaultdict(float)

    with open(args.filename, "r") as fh:
        for what, when, rcvd, xmit in getdata(readlines(fh)):
            if args.perday:
                tsum = f"{when:%Y-%m-%d}"
            elif args.perweek:
                tsum = f"{when:%Y:%W}"
            elif args.permonth:
                tsum = f"{when:%Y-%m}"
            elif args.peryear:
                tsum = f"{when:%Y}"
            else:
                tsum = f"{when:%Y-%m-%d %H}"

            if tsum:
                if what == 'E':
                    e_per[tsum] += rcvd-xmit
                    e_rcvd[tsum] += rcvd
                    e_xmit[tsum] += xmit
                else:
                    g_per[tsum] += rcvd-xmit

    if args.columns:
        for table in (g_per, e_per, e_rcvd, e_xmit):
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
            print("%s %10.5f %10.5f %10.5f %10.5f" % (t, g_per[t], e_per[t], e_rcvd[t], e_xmit[t]))

if __name__=='__main__':
    main()

