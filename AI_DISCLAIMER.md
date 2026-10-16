# AI disclaimer

This project is developed by [Leo Monteiro](https://github.com/lmonteirotech) together with **Claude Sonnet 5.5**, an AI model made by
Anthropic, which is his development partner: it writes and edits code and documentation, runs tests and drafts texts, and Leo decides what
is built, reads and tests what comes out, and answers for it.

What this means for you:

- **The author is a person.** The commits are Leo's, and so are the decisions and the responsibility. The AI is a tool and a partner, not an
  author or a contributor of the repository, and it is not listed as one.
- **Everything is checked, but mistakes happen.** The generator and the packages are tested (see `tools/mapgen/test_osm.py` and the `REPORT.md`
  every run writes) and tried in the games, but AI-written code can be wrong in ways that are not obvious. Report what you find in
  [Issues](https://github.com/lmonteirotech/openomsi-map-packages/issues).
- **No data of the maps comes from the AI.** The packages are worked out from the maps and from OpenStreetMap (see
  [LICENSE-DATA.md](LICENSE-DATA.md)); the AI writes the code that does it, and takes nothing from the maps' files.
- **The licences are what each file says.** The generator code and the documents are MIT ([LICENSE](LICENSE)); the OpenStreetMap data is ODbL ([LICENSE-DATA.md](LICENSE-DATA.md)); the **Map Package Creator** app is proprietary freeware under its own [EULA](app/EULA.txt). The AI does not change any of them: whatever it wrote is released by Leo under the licence of the part it belongs to.
