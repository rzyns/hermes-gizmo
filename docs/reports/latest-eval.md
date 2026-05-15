# Tool Slimmer Eval Report

| Metric | Value |
|---|---:|
| Prompts | 2 |
| Expected prompts | 2 |
| Hit rate | 1.0 |
| Average selected tools | 6.5 |
| Average reduction | 8.6% |
| Fail-open count | 0 |

| Prompt | Expected hit | Reduction | Fail-open | Selected |
|---|---:|---:|---:|---|
| repo_search | True | 17.1% | False | terminal, read_file, search_files, mcp_github_search_issues, web_search, github_search_code |
| browser_task | True | 0.0% | False | terminal, read_file, search_files, github_search_code, browser_navigate, mcp_github_search_issues, web_search |
