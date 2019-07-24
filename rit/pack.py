import struct
import hashlib
import binascii
import zlib
import rit
import os


def get_int(data, obj=False):
    a = data[0]
    obj_type = (a>>4) & 0b111

    data = data[1:]
    cur = a
    if obj:
        size = a&0xf
    else:
        size = a&0x7f
    n = 1
    while (1 & (cur >> 7)):
        cur = data[0]
        sz = cur&0b1111111
        data = data[1:]
        if obj:
            sz <<= (4 + 7*(n-1))
        else:
            size <<= 7
        size += sz
        n += 1

    if not obj:
        for i in range(1, n):
            size += 2**(7*i)

    return size, data, obj_type, n

class IndexParser:
    def __init__(self, data):
        self.data = data

    def parse(self):
        data = self.data
        header,data = data[:4], data[4:]
        ver,data = data[:4], data[4:]
        layer1,data = data[:1024], data[1024:]

        num = struct.unpack(">I", layer1[-4:])[0]
        layer2 = [data[20*i:20*(i+1)] for i in range(num)]
        data = data[20*num:]
        layer3 = [struct.unpack(">I", data[4*i:4*(i+1)])[0] for i in range(num)]
        #print(layer3)
        data = data[4*num:]
        layer4 = [struct.unpack(">I", data[4*i:4*(i+1)])[0] for i in range(num)]
        data = data[4*num:]
        pack_chk,data = data[:20], data[20:]
        idx_chk,data= data[:20], data[20:]
        #print(pack_chk)
        #print(idx_chk)
        return Index(layer1, layer2, layer3, layer4)
        #return zip(layer2, layer4)


class Index:
    def __init__(self, layer1, layer2, layer3, layer4):
        self.layer1 = layer1
        self.layer2 = layer2
        self.layer3 = layer3
        self.layer4 = layer4


def create_index(objects, sha):
    data = b'\xfftOc\x00\x00\x00\x02'
    layer1 = [0]*256
    for obj in objects:
        h = obj.hash[0]
        for i in range(h, 256):
            layer1[i] += 1

    s_objs = sorted(objects, key=lambda o: o.hash)

    for i in layer1:
        data += struct.pack(">I", i)

    for obj in s_objs:
        data += obj.hash

    for obj in s_objs:
        data += struct.pack(">I", obj.crc)

    for obj in s_objs:
        data += struct.pack(">I", obj.offset)

    data += sha
    data += hashlib.sha1(data).digest()
    return data


def apply_delta(delta, base):
    output = b""
    _, delta, _, _ = get_int(delta, obj=False)
    _, delta, _, _ = get_int(delta, obj=False)
    while delta:
        inst,delta = delta[0], delta[1:]
        action = (inst >> 7) & 1
        if action == 1:
            arr = [0]*7
            for i in range(7):
                if (inst >> i) & 1:
                    arr[i],delta = delta[0],delta[1:]
            off_arr = bytes(arr[:4])
            siz_arr = bytes(arr[4:]) + b'\x00'
            offset = struct.unpack("<I", off_arr)[0]
            size = struct.unpack("<I", siz_arr)[0]
            output += base[offset:offset+size]
        elif action == 0:
            num = inst & 0x7f
            output += delta[:num]
            delta = delta[num:]
    return output


class PackfileEntry:
    def __init__(self, size, obj_type, output, n, unused):
        self.size = size
        self.obj_type = obj_type
        self.output = output
        self.n = n
        self.unused = unused
        self.crc = 0
        self.offset = 0


class PackParser:
    def __init__(self, data, index=None):
        self.data = data
        self.index = index
        self.objects = []

    def parse_object(self, offset):
        data = self.data[offset:]
        size, data, obj_type, n = get_int(data, obj=True)
        if obj_type == 6:
            i,data,_,n1 = get_int(data, obj=False)
            zobj = zlib.decompressobj()
            delta = zobj.decompress(data)
            neg_offset = offset - i

            e = self.parse_object(neg_offset)

            output = apply_delta(delta, e.output)
            l = len(data) - len(zobj.unused_data)
            entry = PackfileEntry(
                    size, e.obj_type, output, n+n1, l)
            d = self.data[offset:offset+n+n1+l]
            entry.crc = zlib.crc32(d)
            return entry
            
        else:
            zobj = zlib.decompressobj()
            output = zobj.decompress(data)
            l = len(data) - len(zobj.unused_data)
            entry = PackfileEntry(size, obj_type, output, n, l)
            d = self.data[offset:offset+n+l]
            entry.crc = zlib.crc32(d)
            return entry
            #return size, obj_type, output, n, len(data) - len(zobj.unused_data)

    def parse_without_index(self):
        header = self.data[:4]
        version = self.data[4:8]
        numobj = struct.unpack(">I", self.data[8:12])[0]

        #print(header)
        #print(version)
        #print(numobj)
        #print("*"*30)

        objects = []
        offset = 12
        for _ in range(numobj):
            #print(offset)
            e = self.parse_object(offset)
            #s,o,output,n,z = self.parse_object(offset)
            e.offset = offset
            offset += e.unused + e.n
            objects.append(e)
            #objects.append((e.output, e.obj_type, offset, e.crc))

        new_objects = []
        #for output, o, offset, crc in objects:
        for obj in objects:
            o = obj.obj_type
            l = len(obj.output)
            if o == 1:
                out = f"commit {l}".encode() + b"\x00"
            # tree
            elif o == 2:
                out = f"tree {l}".encode() + b"\x00"
            # blob
            elif o == 3:
                out = f"blob {l}".encode() + b"\x00"
            out += obj.output
            h = hashlib.sha1(out).digest()
            obj.hash = h
            obj.obj_data = out
            #new_objects.append((h, out, offset, crc))
        sha = self.data[-20:]
        self.sha = sha
        self.objects = objects
    
    def create_index(self):
        return create_index(self.objects, self.sha)
 
    def parse_with_index(self):
        header = self.data[:4]
        version = self.data[4:8]
        numobj = struct.unpack(">I", self.data[8:12])[0]

        #print(header)
        #print(version)
        #print(numobj)
        #print("*"*30)

        objects = []
        offsets = []
    
        if not self.index:
            return
    
        z = zip(self.index.layer2, self.index.layer4)
        for item, offset in z:
            offsets.append(offset)
            e = self.parse_object(offset)
            e.hash = item
            self.objects.append(e)

            #_,o,output,_,_ = self.parse_object(offset)
            #self.objects.append((item, e.output, e.obj_type))
        self.sha = self.data[-20:]

    def write_objects(self, objdir):
        #for hsh, output, o in self.objects:
        for obj in self.objects:
            hsh = obj.hash
            output = obj.output
            o = obj.obj_type
            l = len(output)
            # commit
            if o == 1:
                out = f"commit {l}".encode() + b"\x00"
            # tree
            elif o == 2:
                out = f"tree {l}".encode() + b"\x00"
            # blob
            elif o == 3:
                out = f"blob {l}".encode() + b"\x00"
            out += output
            _h = hashlib.sha1(out).digest()
            assert _h == hsh
            z = zlib.compress(out)
            
            h = binascii.hexlify(_h).decode()
            path = os.path.join(objdir, h[:2], h[2:])
            dirname = os.path.dirname(path)

            if not os.path.isdir(dirname):
                os.mkdir(dirname)
            if os.path.isfile(path):
                os.chmod(path, 0o644)
            with open(path, "wb") as f:
                f.write(z)
            os.chmod(path, 0o444)


