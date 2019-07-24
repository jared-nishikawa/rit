import urllib.request

url = "https://gitlab.com/jared-n/rit.git/info/refs?service=git-upload-pack"
req = urllib.request.urlopen(url)
data = req.read()
print(data.decode())
print("*"*80)
exit()


url = "https://gitlab.com/jared-n/rit.git/git-upload-pack"
body = b"0098want 43e383a96d5bca5ab32855659849a51384a3778b multi_ack_detailed no-done side-band-64k thin-pack ofs-delta deepen-since deepen-not agent=git/2.17.1\n00000009done\n"
#body = b"want 43e383a96d5bca5ab32855659849a51384a3778b\n"
#l = f"{len(body) + 4:04x}".encode()
#body = l + body
#body += b"00000009done\n"
req = urllib.request.Request(url, body)
#req.add_header("Accept-Encoding", "gzip")
req.add_header("Content-Type", "application/x-git-upload-pack-request")
#req.add_header('Accept', 'application/x-git-upload-pack-result')

r = urllib.request.urlopen(req)
data = r.read()
with open('response.data', 'wb') as f:
    f.write(data)

