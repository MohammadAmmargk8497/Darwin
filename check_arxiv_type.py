import arxiv

def check():
    query = "Proximal Policy Optimization"
    # Test with string max_results to see if it fails
    try:
        print("Testing with string max_results='5'")
        search = arxiv.Search(
            query=query,
            max_results="5",
            sort_by=arxiv.SortCriterion.Relevance
        )
        client = arxiv.Client()
        # triggering the generator
        results = list(client.results(search))
        print(f"Success! Found {len(results)} results.")
    except Exception as e:
        print(f"Failed as expected: {e}")

    # Test with int cast
    try:
        print("\nTesting with int('5')")
        search = arxiv.Search(
            query=query,
            max_results=int("5"),
            sort_by=arxiv.SortCriterion.Relevance
        )
        client = arxiv.Client()
        results = list(client.results(search))
        print(f"Success! Found {len(results)} results.")
    except Exception as e:
        print(f"Failed: {e}")

if __name__ == "__main__":
    check()
