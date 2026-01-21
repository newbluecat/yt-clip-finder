import sys
import os

def main():
    print("--------------")
    print(sys.executable)
    print(os.path.abspath(__file__))
    print("--------------")


if __name__ == "__main__":
    main()
