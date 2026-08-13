import seed_data
import sys

email = sys.argv[1]
print("seeding:", email)
ok = seed_data.seed_tenant(email)
print("seeded:", ok)