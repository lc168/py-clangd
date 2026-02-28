import sys
import os
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(current_dir, ".."))
sys.path.append(parent_dir)

from database import Database

db = Database("cases/pyclangd_index.db")
usr = db.get_usr_at_location(os.path.join(current_dir, "cases", "test_kernel_use.c"), 36, 28)
print(f"USR for container_of: {usr}")
if usr:
    print(db.get_definitions_by_usr(usr))

usr2 = db.get_usr_at_location(os.path.join(current_dir, "cases", "test_kernel_use.c"), 39, 28)
print(f"USR for list_entry: {usr2}")
if usr2:
    print(db.get_definitions_by_usr(usr2))
