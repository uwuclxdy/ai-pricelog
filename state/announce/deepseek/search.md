Search & Fetch | DeepSeek API Docs Skip to main content Search / Fetch API is now available, powered by our in-house search engine and supporting web search and fetch.
Click here to view the guide.
DeepSeek API Docs Resources Integrations API Status FAQ English English 中文（中国） DeepSeek Platform 中 Quick Start API Guides API Reference News Change Log Vision Thinking Mode Multi-round Conversation Chat Prefix Completion (Beta) FIM Completion (Beta) JSON Output Tool Calls Files API Search & Fetch Context Caching Using the Responses API Using the Anthropic API Search & Fetch On this page Search & Fetch The Search API and the Fetch API give agents and RAG applications access to live web content: Search API finds web pages for a query and returns structured results.
It is powered by DeepSeek's in-house search engine.
Fetch API retrieves a single web page and returns its content as Markdown.
Both are raw JSON APIs.
They use the same bearer authentication as the DeepSeek API.
The base URL is https://api.deepseek.com : API Endpoint Search POST https://api.deepseek.com/v1/tools/search Fetch POST https://api.deepseek.com/v1/tools/fetch See the Search API Reference and Fetch API Reference for the complete request and response schemas.
Authentication ​ Send your API key and the JSON content type in the request headers: Header Required Value Authorization Yes Bearer <DeepSeek API Key> Content-Type Yes application/json Search API ​ Request ​ curl https://api.deepseek.com/v1/tools/search \ -H "Authorization: Bearer <DeepSeek API Key>" \ -H "Content-Type: application/json" \ -d '{ "query": "DeepSeek V4 release", "count": 5, "need_content": true }' import requests response = requests .
post ( "https://api.deepseek.com/v1/tools/search" , headers = { "Authorization" : "Bearer <DeepSeek API Key>" , } , json = { "query" : "DeepSeek V4 release" , "count" : 5 , "need_content" : True , } , ) response .
raise_for_status ( ) for result in response .
json ( ) [ "results" ] : print ( result [ "title" ] , result [ "url" ] ) print ( result [ "summary" ] ) Request fields: Field Type Required Default Description query string Yes - The search query must contain 1 to 128 Unicode characters, cannot be all whitespace, and supports the query operators listed below.
count integer No 10 The number of results to return, between 1 and 50.
ori_question string No - The user's original question that triggered the search, between 1 and 128 characters, to improve query understanding, with null treated as not provided.
localization string No "" An optional IP address used to localize search results.
need_content boolean No false Whether to return page content in content , which is always an empty string when false .
Unknown fields in the request body are ignored.
Query Operators ​ The query is forwarded with its search syntax intact.
The examples below combine operators with a search term; you can combine multiple operators in one query.
Operator Example Description site: DeepSeek site:github.com Restrict results to the given site, and to target multiple sites, separate the site: clauses with spaces and join them with OR , for example DeepSeek site:github.com OR site:huggingface.co .
-site: DeepSeek -site:example.com Exclude the given site, and separate multiple sites with spaces.
- DeepSeek -advertisement Exclude pages containing the term, and separate multiple terms with spaces.
-"..." DeepSeek -"release notes" Exclude pages containing the exact phrase, which can contain spaces, and separate multiple phrases with spaces.
"..." DeepSeek "exact phrase" Match an exact phrase, and separate multiple phrases with spaces.
lang: DeepSeek lang:zh,en Restrict results to the given language codes, separating multiple codes with commas, for example lang:zh,en .
after: DeepSeek after:2025 or DeepSeek after:2025-01-01 Restrict results to pages published after a date.
before: DeepSeek before:2026 or DeepSeek before:2026-06-01 Restrict results to pages published before a date.
For example: { "query": "DeepSeek site:github.com OR site:huggingface.co lang:en after:2025", "count": 10 } Response ​ A successful request returns HTTP 200 with a results array.
A normal search with no matches returns an empty array.
{ "results": [ { "rerank_score": 2.4, "title": "DeepSeek V4 model released", "url": "https://example.com/deepseek-v4", "snippet": "DeepSeek V4 is now available, with tool calling and long-context support.", "summary": "DeepSeek has released the V4 model.
The release adds improved tool calling and long-context support for agent workflows.", "content": "DeepSeek V4 is now generally available...", "site_name": "Example News", "site_icon": "https://example.com/favicon.ico", "date": "2026-06-01T00:00:00+00:00", "authority": 3 } ] } Each item in results contains: Field Type Description rerank_score number A relevance score from 0 to 3 that combines signals such as relevance, authority, and freshness, with scores of 1.5 or above considered high-quality results.
title string The title of the result.
url string The URL of the result.
snippet string A short summary related to the query, typically 100 to 200 characters, intended for display in a UI.
summary string A long summary related to the query, typically 600 to 800 characters, intended to be read by a model.
content string The page content, which is empty when need_content is false or when the content is unavailable.
site_name string or null The name of the site, or null when unavailable.
site_icon string or null The URL of the site icon, or null when unavailable.
date string or null The publication time in UTC, formatted as RFC 3339, or null when unknown.
authority integer The authority tier of the page, 0 to 4 ( -1 means unknown), with values of 3 or above indicating highly authoritative sources.
Fetch API ​ Request ​ curl https://api.deepseek.com/v1/tools/fetch \ -H "Authorization: Bearer <DeepSeek API Key>" \ -H "Content-Type: application/json" \ -d '{ "url": "https://example.com/article" }' import requests response = requests .
post ( "https://api.deepseek.com/v1/tools/fetch" , headers = { "Authorization" : "Bearer <DeepSeek API Key>" , } , json = { "url" : "https://example.com/article" } , ) response .
raise_for_status ( ) page = response .
json ( ) print ( page [ "title" ] ) print ( page [ "content" ] ) Request fields: Field Type Required Description url string Yes The page URL to fetch, which must be at most 8192 characters, an HTTP or HTTPS URL with a host, and must not contain a username or password.
Response ​ { "title": "Example article", "content": "# Example article\n\nArticle content." } Field Type Description title string The title of the page, empty when the title is unavailable.
content string The fetched page content as Markdown text.
Fetching is subject to the target site's availability and access policies.
Errors ​ Errors follow the OpenAI-compatible error format.
The param field is always null .
{ "error": { "message": "'count' must be between 1 and 50", "type": "invalid_request_error", "param": null, "code": "invalid_request_error" } } HTTP Status Description 400 The request headers or body are invalid, including malformed JSON or an invalid field value.
401 The API key is missing or invalid.
402 The account has insufficient balance.
403 The Fetch request was rejected by the security policy.
404 Fetch could not retrieve usable page content, for example due to an unavailable URL, a URL blocked by site policy, an error from the target site, an unsupported content type, or a page with no extractable Markdown content.
408 Reading the request body timed out.
413 The request body is too large.
429 The Search or Fetch QPS limit was exceeded.
500 An internal server error occurred.
504 A downstream request timed out.
Search and Fetch are read-only.
For HTTP 408, 429, or 5xx errors, wait and retry.
For HTTP 402, top up your account before retrying.
Do not retry other 4xx errors without changing the request.
Billing ​ Search and Fetch are billed per successful request, not by tokens or by the number of returned results: API Unit Price Search Per 1,000 successful requests $0.75 Fetch Per 1,000 successful requests $0.75 A request is billable only when it returns HTTP 200 and produces a result (Search must return a non-empty results array, and Fetch must return page content).
Failed requests, empty search results, and timeouts are not billed.
count only controls how many results are returned and does not affect the per-request price.
Note: when you use the DeepSeek API through DeepSeek Harness, Claude Code, or Codex, server-side tool calls already hit the Search and Fetch APIs.
These calls are currently free of charge; per-request billing starts at 00:00 Beijing time on November 1, 2026.
Rate Limits ​ For each account, Search and Fetch are limited independently, and traffic to one does not consume the other's quota: API QPS Limit Search 5 Fetch 5 The QPS (requests per second) limits are calculated at the account level, regardless of which API key is used, and are separate from the model concurrency limits.
Requests above the account-level QPS limit receive HTTP 429.
In addition to the account-level limit, Fetch is also subject to a per-domain QPS limit, and requests above that limit also receive HTTP 429.
Previous Files API Next Context Caching Authentication Search API Request Query Operators Response Fetch API Request Response Errors Billing Rate Limits WeChat Official Account Community Email Discord Twitter More GitHub Copyright © 2026 DeepSeek, Inc.
