"""Build or rebuild the semantic search index from stored FHIR bundles."""

from ehr_media.search.indexer import SearchIndex


def main() -> None:
    count = SearchIndex().rebuild(force=True)
    print(f"Indexed {count} searchable chunks.")


if __name__ == "__main__":
    main()