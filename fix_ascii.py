import os

def fix_ascii(directory):
    for root, dirs, files in os.walk(directory):
        if "__pycache__" in dirs:
            dirs.remove("__pycache__")
        for file in files:
            if file.endswith((".py", ".md", ".html", ".css", ".txt")):
                path = os.path.join(root, file)
                try:
                    with open(path, "rb") as f:
                        content = f.read()
                    
                    # Filter only ASCII characters
                    cleaned = bytes([b for b in content if b < 128])
                    
                    if cleaned != content:
                        with open(path, "wb") as f:
                            f.write(cleaned)
                        print(f"Fixed: {path}")
                except Exception as e:
                    print(f"Error processing {path}: {e}")

if __name__ == "__main__":
    fix_ascii(".")
