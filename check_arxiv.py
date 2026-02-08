import arxiv

def check():
    query = "Proximal Policy Analysis"
    print(f"Searching for: {query}")
    client = arxiv.Client()
    search = arxiv.Search(
        query=query,
        max_results=5,
        sort_by=arxiv.SortCriterion.Relevance
    )
    
    for r in client.results(search):
        print(f"ID: {r.get_short_id()} | Title: {r.title}")

if __name__ == "__main__":
    check()
