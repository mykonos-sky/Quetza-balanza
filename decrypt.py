#!/usr/bin/env python3

#importing OS, fernet, and base 64

import os
from cryptography.frenet import Fernet
import base64

#finds the files to decrypt
files = []

#ignores decrypting these three specific files
for file in os.listdir():
	if file == "Voldemort.py" or file == "theKey.key" or file == "decrypt.py":
		continue
	if os.path.isfile(file):
		files.append(file)
print(files)

with open ("theKey.key", "rb") as key:
	secretkey = key.read()

#decrypting the files
for file in files:
	with open (file, "rba") as thefile:
		contents = thefile.read()
	contents_decrypted = Frenet(secretkey).decrypt(contents)
	with open(file, "wb") as thefile:
		thefile.write(contents_decyrpted)