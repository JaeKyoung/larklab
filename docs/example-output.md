# Example output

## Terminal

```
Fetching Scholar emails from the last 7 days...
Found 10 emails, detecting batches...
Found 2 batches: Batch 1 (6 emails, 03/19 07:16) | Batch 2 (4 emails, 03/17 08:30)
Processing 10 emails.
Parsed 25 papers total.

============================================================
  Google Scholar Digest — 25 papers, 2 days
============================================================

--- 2026-03-18 (15 papers) ---

  1. Paper Title Here
     Authors: A Author, B Author
     Journal: Nature, 2026
     Abstract: Lorem ipsum dolor sit amet...
     URL: https://doi.org/10.1234/example
     Top 1 related paper (similarity: 0.823)
     Reference Paper Alpha
     Top 2 related paper (similarity: 0.756)
     Reference Paper Beta
     Top 3 related paper (similarity: 0.691)
     Reference Paper Gamma

  ...

Sent 2 batch(es) to #journal-club (25 papers total)
Trashed 10 processed emails.
```

## Slack

Each batch is a headline message with one threaded card per paper:

```
*Scholar Digest — 2026-03-18*
• 15 papers
  ┃ Nature, 2026
  ┃ Paper Title Here
  ┃ Lorem ipsum dolor sit amet, consectetur adipiscing elit...
  ┃ Authors: A Author, B Author
  ┃ Top 1 related paper (similarity: 0.823): Reference Paper Alpha
  ┃ Top 2 related paper (similarity: 0.756): Reference Paper Beta
  ┃ Top 3 related paper (similarity: 0.691): Reference Paper Gamma
```

`recommend` posts one thread per publication date, with a headline such as `• arxiv: 3/40` (recommended / candidates scored).

## `--output-json`

`digest --output-json out.json` writes everything a downstream script needs:

```json
{
  "generated_at": "2026-03-19T08:00:12",
  "num_emails": 10,
  "num_parsed": 25,
  "digests": [
    {
      "date": "2026-03-18",
      "papers": [
        {
          "title": "Paper Title Here",
          "authors": ["A Author", "B Author"],
          "journal": "Nature, 2026",
          "abstract": "Lorem ipsum...",
          "url": "https://doi.org/10.1234/example",
          "received_at": "2026-03-18T07:16:00+00:00",
          "summary": "",
          "doi": "10.1234/example",
          "similar_papers": [["Reference Paper Alpha", 0.823]]
        }
      ]
    }
  ]
}
```
