# PDF-Comic-Spread-Joiner

This is a project intended to be used with Kindle comic converter to combine seperated 2 page spreads into a singular page.

The App can be used in 2 ways, either manual input of page numbers that are part of a 2 page spread or via importing a JSON file with page number of 2 page spreads and a Manga value that will swap the left and right side of spread.

An example of the JSON structure from Vinland Saga Vol1 

`[
  {
    "start_page": 4,
    "end_page": 5,
    "rtl": true
  },
  {
    "start_page": 48,
    "end_page": 49,
    "rtl": true
  },
  {
    "start_page": 90,
    "end_page": 91,
    "rtl": true
  },
  {
    "start_page": 136,
    "end_page": 137,
    "rtl": true
  },
  {
    "start_page": 286,
    "end_page": 287,
    "rtl": true
  },
  {
    "start_page": 370,
    "end_page": 371,
    "rtl": true
  },
  {
    "start_page": 390,
    "end_page": 391,
    "rtl": true
  },
  {
    "start_page": 424,
    "end_page": 425,
    "rtl": true
  }
]`