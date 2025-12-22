
p = 'оплат'
t = 'оплачую'

print(f"Pattern: {p}")
for i, c in enumerate(p):
    print(f"  {i}: {c} (U+{ord(c):04X})")

print(f"Text: {t}")
for i, c in enumerate(t[:5]):
    print(f"  {i}: {c} (U+{ord(c):04X})")

print(f"Match: {p in t}")
