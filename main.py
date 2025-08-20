import os
from dotenv import load_dotenv
from src.gui import App

def main():
    app = App()
    app.mainloop()

if __name__ == "__main__":
    main()