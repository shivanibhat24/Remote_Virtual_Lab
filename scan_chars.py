import os

def scan_non_ascii(directory):
    non_ascii_found = False
    for root, dirs, files in os.walk(directory):
        if ".git" in dirs:
            dirs.remove(".git")
        if "__pycache__" in dirs:
            dirs.remove("__pycache__")
            
        for file in files:
            if file.endswith((".py", ".md", ".html", ".css", ".txt")):
                path = os.path.join(root, file)
                try:
                    with open(path, "rb") as f:
                        content = f.read()
                        for i, byte in enumerate(content):
                            if byte > 127:
                                line_no = content[:i].count(b'\n') + 1
                                print(f"Found non-ASCII at {path}:{line_no} (byte: {byte})")
                                non_ascii_found = True
                                break
                except Exception as e:
                    print(f"Error reading {path}: {e}")
    if not non_ascii_found:
        print("Total ASCII compliance achieved!")

if __name__ == "__main__":
    scan_non_ascii(".")
