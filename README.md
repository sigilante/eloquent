# Eloquent

[Gwern suggested](https://gwern.net/resorter) using Elo relative rankings to rate items based on pairwise comparisons.  He supplied an R implementation, `resorter`.

This is a Python implementation of the same idea, with a simple key-driven browser UI.

![](./img/hero.jpg)

## Usage

1. Install Python 3.8+ and `pip`.

2. Install dependencies:

   ```bash
   cd src
   pip install -r requirements.txt
   ```

3. Supply a list of items to be ranked in a text file (see Data Sources below for examples).

4. Start the server:

   ```bash
   python app.py
   ```

5. Navigate to `http://localhost:5000` in your web browser and select your source file.

6. Rank items by clicking on the left or right item, or pressing the left or right arrow key.  The selected item will gain Elo points, and the other item will lose points.  The up and down arrows move back in history and skip forwards, respectively.

7. To serve to the web, use:

    ```bash
    gunicorn -w 4 -b 0.0.0.0:8000 --timeout 120 app:app
    ```

## Data Sources

Text lists are simply newline-delimited text files, with each line being an item to be ranked.

* `actresses.txt` file contains a list of actresses, one per line, drawn from the [Encyclopedia Britannica](https://www.britannica.com/topic/list-of-actresses-2021631).
* `books.txt` is [Modern Library's 100 Best Novels and 100 Best Nonfiction Books](https://sites.prh.com/modern-library-top-100/#top-100-novels).
