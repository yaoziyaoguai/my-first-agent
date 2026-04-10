import os

print("当前目录下的文件和文件夹：")
print("-" * 40)

for item in os.listdir('.'):
    if os.path.isdir(item):
        print(f"[文件夹] {item}")
    else:
        print(f"[文件]   {item}")
