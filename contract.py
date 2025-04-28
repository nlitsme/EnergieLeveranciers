import os
import re
import json

def get(d, *path):
    for p in path:
        if d is None:
            return
        if type(d)==dict and type(p)==str:
            d = d.get(p)
        elif type(d)==list and type(p)==int:
            if p<0 or p>=len(d):
                return
            d = d[p]
    return d

def printproduct(p):
    print(f"{get(p,'startDate')}: {get(p,'type','name')} {get(p,'description')}")
    details = get(p, 'productRate', 'productRateDetails') \
            or get(p, 'unitRates') \
            or []
    for r in details:
        print(f"  {get(r,'vatIncluded') or get(r,'vat','vatIncluded'):>10.5f} - {get(r,'description')}")

def printproducts(plist):
    for prod in plist:
        printproduct(prod)
def process_products(fh):
    for line in fh:
        if line.startswith('nothing to do, specify'):
            # ignore message
            pass
        elif line.startswith('auth: status = UNAUTHENTICATED'):
            pass
        elif line.startswith(' factor password'):
            pass
        elif line.startswith('auth: status = SUCCESS'):
            pass
        elif line.startswith('auth: status = MFA_REQUIRED'):
            break
        elif line.startswith('urllib.error.URLError'):
            pass
        elif line.startswith('Traceback'):
            pass
        elif line.startswith('socket.gaierror'):
            pass
        elif line.startswith('Exception: MFA_REQUIRED'):
            pass
        elif line.startswith('During handling of'):
            pass
        elif line.startswith('WARNING: failed to get token'):
            pass
        elif line.startswith('WARNING: failed to get id-token'):
            pass
        elif line.find('<!DOCTYPE') > 0:
            pass
        elif line.startswith('    '):
            pass  # ignore part of traceback
        elif line.startswith('  File '):
            pass  # ignore part of traceback
        else:
            data = None
            if line.startswith("{'"):
                data = eval(line)
            elif line.startswith('{"'):
                data = json.loads(line)
            elif len(line)>1:
                print("??", line)

            plist = get(data, 'data')
            if type(plist) == dict:
                plist = plist.get('products')
            return plist

def process_log(fh):
    pass

def printmodel(m):
    for price, desc in m:
        print(f"{price:>8s} - {desc}")

def process_model(fh):
    l = list()
    html = fh.read()
    for m in re.finditer(r'<tr>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*</tr>', html, re.DOTALL):
        desc, price = m.groups()
        price = re.sub(r"&\w+;", '', price)
        price = price.lstrip()

        l.append((price, desc))
    return l
def main():
    prodbydate = dict()
    modbydate = dict()
    for _, _, flist in os.walk('logs'):
        for filename in flist:
            if m := re.match(r'prod-(\d+-\d+)', filename):
                dt = m[1]
                prods = process_products(open(os.path.join('logs',filename), 'r'))
                if prods:
                    prodbydate[dt] = prods
            elif filename.startswith('log-'):
                pass #process_log(open(os.path.join('logs',filename), 'r'))
            elif m := re.match(r'model-(\d+-\d+)', filename):
                dt = m[1]
                model = process_model(open(os.path.join('logs',filename), 'r'))
                if model:
                    modbydate[dt] = model
            else:
                print("?", filename)

    print("---------- products --------")
    tstart = None
    tprev = None
    pcur = None
    for t, p in sorted(prodbydate.items()):
        if not tprev:
            tstart = t
            pcur = p
        elif pcur != p:
            print("%s .. %s" % (tstart, tprev))
            printproducts(pcur)
            pcur = p
            tstart = t
        tprev = t
    print("%s .." % tstart)
    printproducts(pcur)

    print("---------- models --------")
    tstart = None
    tprev = None
    pcur = None
    for t, p in sorted(modbydate.items()):
        if not tprev:
            tstart = t
            pcur = p
        elif pcur != p:
            print("%s .. %s" % (tstart, tprev))
            printmodel(pcur)
            pcur = p
            tstart = t
        tprev = t
    print("%s .." % tstart)
    printmodel(pcur)

if __name__=='__main__':
    main()

