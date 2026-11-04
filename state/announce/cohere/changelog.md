Release Notes | Cohere For AI agents: a documentation index is available at the root level at /llms.txt.
Append /llms.txt to any URL for a page-level index, or .md for the markdown version of any page.
docs v2 API v2 API Search / Ask AI DASHBOARD PLAYGROUND DOCS COMMUNITY LOG IN Guides and concepts API Reference Release Notes LLMU Cookbooks Search / Ask AI Skip to navigation This page is for version v2 API (default).
For other versions, use one of these documentation indexes: - v2 API (default): https://docs.cohere.com/v2/llms.txt - v1 API: https://docs.cohere.com/v1/llms.txt On this page November 4, 2026 Available models Getting started November 3, 2026 Key features Calling open models Availability October 21, 2026 Key features Upgrading Example query with Context Focus Availability September 30, 2026 Key features Availability September 9, 2026 Key features Technical details Availability August 27, 2026 Availability July 7, 2026 Technical Details Availability June 9, 2026 Technical Details Availability
May 20, 2026 Key Features Technical Details Availability April 4, 2026 Retirement notice Release Notes Subscribe via RSS November 4, 2026 November 4, 2026 Embed 5 and Rerank 5 Are Now Available on OpenRouter Cohere’s Embed 5 and Rerank 5 models are now available on OpenRouter .
If you build on OpenRouter, you can now add Cohere embeddings and reranking to your search and RAG pipelines with your existing OpenRouter API key.
Available models Embed 5 Pro ( cohere/embed-5-pro ): Optimized for the highest retrieval quality, particularly for offline indexing and quality-critical retrieval.
Embed 5 Fast ( cohere/embed-5-fast ): Optimized for low latency and high throughput, particularly for interactive search, agent loops, and high-volume query traffic.
Rerank 5 Pro ( cohere/rerank-5-pro ): Optimized for the highest ranking quality, particularly for complex, reasoning-heavy queries and long or domain-specific documents.
Rerank 5 Fast ( cohere/rerank-5-fast ): Rerank 5 quality for latency- and cost-sensitive workloads.
Outperforms Rerank 4 Pro.
Embed 5 accepts text, images, and mixed text-and-image inputs such as PDF pages.
Embed 5 Pro and Fast share an embedding space, so you can index your corpus with Pro and embed queries with Fast.
For pricing, see each model’s OpenRouter page.
Getting started See Using Cohere Models on OpenRouter for the full list of Cohere models on OpenRouter, a setup checklist, and the differences from the Cohere API.
For an end-to-end retrieval pipeline, see OpenRouter’s RAG with Embeddings & Rerank cookbook.
For more on the models themselves, see the Embed 5 announcement and the Rerank 5 announcement .
November 3, 2026 November 3, 2026 Open Models and Regional Serving in Model Vault Model Vault and Model Vault Encrypted now run leading third-party open models alongside Cohere’s models, on fully managed, dedicated infrastructure.
You can choose the right model for each task and run every one of them with the same protections.
Key features Open models in Model Vault : deploy models from DeepSeek, Z.ai (GLM), Xiaomi (MiMo), NVIDIA (Nemotron), Google (Gemma), OpenAI (GPT-OSS), Microsoft (Phi), Alibaba (Qwen), and Mistral AI.
See Standard Vault supported models .
Open models in Model Vault Encrypted : run Gemma, GPT-OSS, Phi, Qwen, Devstral, and Ministral with confidential computing, so not even Cohere or the cloud provider can see your prompts or responses.
See Encrypted Vault supported models .
Zero Data Retention by default : prompts and responses are not retained in Model Vault.
Regional serving : Model Vault runs in the United States, the European Union, and Canada.
Model Vault Encrypted runs in the United States, with the European Union and Canada coming soon.
See Regions .
Calling open models Open models are served through the OpenAI-compatible Chat Completions API at your vault endpoint: PYTHON from openai import OpenAI client = OpenAI ( api_key = " <COHERE_API_KEY> " , base_url = " <YOUR_VAULT_ENDPOINT_URL>/v1 " , ) response = client .
chat .
completions .
create ( model = " deepseek-v4-1-flash " , messages = [{ " role " : " user " , " content " : " Hello from Model Vault!
" }], ) print ( response .
choices [ 0 ].
message .
content ) See Calling a Standard Vault over the API and Calling an Encrypted Vault over the API .
Availability Open models are available today in the Model Vault app .
Model Vault is priced per GPU, per hour, for both Standard and Encrypted Vaults; see the pricing page .
For reserved capacity, contact our sales team .
October 21, 2026 October 21, 2026 Announcing Cohere's Rerank 5 Models We’re pleased to announce the release of Rerank 5 , Cohere’s most advanced reranking models for enterprise retrieval: sharper search, with fewer tokens sent to your LLM.
Rerank 5 Pro delivers our highest reranking quality yet, with its largest gains on reasoning-intensive retrieval and in enterprise domains such as finance, healthcare, and scientific research.
Rerank 5 Fast brings that quality to latency- and cost-sensitive workloads, and outperforms our previous-generation Rerank 4 Pro model.
Key features Two model variants available: rerank-v5.0-pro : Optimized for the highest ranking quality, particularly for complex, reasoning-heavy queries and long or domain-specific documents.
rerank-v5.0-fast : Optimized for low latency and high throughput, particularly for high-volume search and agents that run many searches per task.
Context Focus : An optional capability that returns the most relevant passages within each document, as scored character spans, in the same Rerank call.
Pass only those passages to your LLM to cut token costs, or highlight them to show users why a result matched.
Calibrated relevance scores : Scores are consistent across queries and domains, so you can set one threshold to decide which results reach your LLM.
Multilingual support : Supports over 100 languages.
Extended context length : 32k token context window.
Semi-structured data support : Rerank JSON, tables, and other records formatted as YAML strings.
Upgrading Rerank reads raw text at query time, so upgrading doesn’t require re-indexing or re-embedding your corpus.
To upgrade from an earlier Rerank model, update the model parameter to rerank-v5.0-pro or rerank-v5.0-fast .
Context Focus is off by default.
Example query with Context Focus cURL curl --request POST \ --url https://api.cohere.com/v2/rerank \ --header ' accept: application/json ' \ --header ' content-type: application/json ' \ --header " Authorization: bearer $CO_API_KEY " \ --data ' { "model": "rerank-v5.0-pro", "query": "What is the capital of the United States?", "top_n": 3, "documents": [ "Carson City is the capital city of the American state of Nevada.", "The Commonwealth of the Northern Mariana Islands is a group of islands in the Pacific Ocean.
Its capital is Saipan.", "Washington, D.C.
(also known as simply Washington or D.C., and officially as the District of Columbia) is the capital of the United States.
It is a federal district.", "Capitalization or capitalisation in English grammar is the use of a capital letter at the start of a word.
English usage varies from capitalization in other languages.", "Capital punishment has existed in the United States since before the United States was a country.
As of 2017, capital punishment is legal in 30 of the 50 states." ], "relevant_spans": { "mode": "enabled", "threshold": 0.3, "max_spans": 10 } } ' Each result includes its relevance_score and, where passages meet the threshold , a relevant_spans list with the start and end character offsets of each passage in the original document and its score .
Availability Rerank 5 is available through the Rerank API , as well as Microsoft Foundry ( Pro , Fast ) and Amazon SageMaker ( Pro , Fast ).
For deployment on dedicated infrastructure, Rerank 5 is also available in Cohere’s Model Vault (see Model Vault pricing ).
For private deployments in your own VPC or on-premises, contact our sales team .
For more details, see the model documentation , the Rerank overview , and the best practices guide .
September 30, 2026 September 30, 2026 Announcing Cohere's Embed 5 Models We’re pleased to announce the release of Embed 5 , Cohere’s most powerful embeddings family yet.
Embed 5 delivers frontier retrieval quality on complex enterprise data, with major gains over Embed 4 on visually rich documents, financial filings, parsed PDFs, code, and multilingual retrieval.
Key features Two model variants available: embed-v5.0-pro : Optimized for the highest retrieval quality, particularly for offline indexing and quality-critical retrieval embed-v5.0-fast : Optimized for low latency and high throughput, particularly for interactive search, agent loops, and high-volume query traffic Shared embedding space : Pro and Fast share an embedding space, so a corpus indexed with one model can be queried with the other.
We recommend indexing with Pro and querying with Fast.
Multimodal inputs : Embed text, images, and mixed text-and-image inputs (e.g.
PDF pages) in a single vector Multilingual support : Supports over 100 languages Extended context length : 128k token context window Flexible storage : Matryoshka embeddings in the following dimensions: [256, 512, 768, 1024, 1536, 2048] , with float , int8 , and binary output types Availability Embed 5 is available through the Embed API , as well as Microsoft Foundry ( Pro , Fast ) and Amazon SageMaker ( Pro , Fast ).
For deployment on dedicated infrastructure, Embed 5 is also available in Cohere’s Model Vault .
For more details, see the model documentation .
September 9, 2026 September 9, 2026 Announcing Cohere's North Small Translate We’re pleased to announce the release of North Small Translate , an open-weights mixture-of-experts model purpose-built for machine translation across more than 50 languages.
North Small Translate is designed to give researchers, developers, and enterprises flexible ways to evaluate and deploy machine translation while retaining control over their data and infrastructure.
Key features Purpose-built translation : Optimized for machine translation across more than 50 languages and locale variants.
Efficient MoE architecture : 218 billion total parameters with 25 billion active parameters.
Flexible deployment : Available through the free-tier Chat V2 API and as open weights in W4A16, FP8, and BF16 for non-commercial use.
Private deployment : Suggested deployment hardware by quantization format: W4A16 : Two H100s or one B200 FP8 : Four H100s or two B200s BF16 : Eight H100s or four B200s Technical details Model name : north-small-translate-1.0 Context length : 16K License : Creative Commons Attribution-NonCommercial 4.0 Open-weights formats : W4A16, FP8, and BF16 Availability North Small Translate is available on the free tier through the Chat V2 API .
Open weights are available in W4A16, FP8, and BF16 on Hugging Face for non-commercial use under the CC BY-NC 4.0 license.
For supported languages, use cases, and an API example, see the model documentation .
August 27, 2026 August 27, 2026 Meet Cohere Parse Today we are releasing Cohere Parse .
Parse (model ID: parse-v5.0 ) turns complex documents into clean, structured Markdown ready for downstream AI workflows.
The 2.3B-parameter multimodal model extracts text in reading order, tables, lists, forms, images and captions, page boundaries, and visual element locations.
Outputs include Markdown/HTML content, HTML-formatted tables, bounding boxes, and image descriptions — preserving both document structure and layout for easier rendering and processing.
Key specs: 8K context window · ~4.6GB model size · Markdown output Availability Cohere Parse is available through the Parse API, as well as Microsoft Foundry and AWS SageMaker .
For deployment on dedicated infrastructure, Parse is also available in Model Vault .
For more details, see the model documentation .
July 7, 2026 July 7, 2026 Meet Cohere Transcribe Arabic Today we are releasing Cohere Transcribe Arabic .
This open-source speech-to-text model is a fine-tune of Cohere Transcribe using Arabic speech data.
It lets Arabic speakers transcribe their voice with unmatched accuracy and support for regional dialects or speech patterns.
It is currently the most accurate open-source Arabic ASR model available today and is optimized for production inference and throughput.
Technical Details Model Name : cohere-transcribe-arabic-07-2026 Size : 2B Architecture : conformer-based encoder-decoder Languages supported : Arabic (all major dialects), English (including English spoken with an Arabic accent) License : Apache 2.0 Availability Cohere Transcribe Arabic is available through the V2 Audio Transcriptions API and as open weights on Hugging Face .
For production use, Model Vault deployment is also supported.
For more details, see the model documentation .
June 9, 2026 June 9, 2026 Announcing Cohere's North Mini Code We’re pleased to announce the release of North Mini Code , Cohere’s first agentic coding model.
It is a 30 billion total / 3 billion active parameter Mixture of Experts model trained specifically for agentic coding, with a small enough active footprint to run on local hardware.
Technical Details Model Name : north-mini-code-1.0 Context Length : 256K input, 64K output License : Apache 2.0 Availability North Mini Code is available through the Chat V2 API and as open weights on Hugging Face.
For production use, Model Vault deployment is also supported.
For more details, see the model documentation .
May 20, 2026 May 20, 2026 Announcing Cohere's Command A+ We’re pleased to announce the release of Command A+ , the last model in the Command A family of models, combining support for vision inputs, reasoning capabilities, translation capabilities, and agentic tasks all within the same model.
It is also notably our first Mixture of Experts (MoE) model with 25 billion active parameters ands 218 billion total parameters.
Key Features Agentic Applications : With notable performance increases in tool use and agentic tasks, Command A+ is the strongest agentic model in the Command family.
Expanded Multilingual Support : With 48 languages supported, including all official EU languages, this more than doubles the support of languages from our prior models.
Efficient & Fast : With as few as 1 x B200 or 2 x H100s required to deploy the model, and up to 110% throughput increase and 30% decrease in latency over Command A Reasoning, the model is designed for production-grade deployments.
Technical Details Model Name : command-a-plus-05-2026 Context Length : 128K input, 64K output Languages covered : English, Arabic, Bulgarian, Bengali, Catalan, Czech, Danish, German, Greek, Spanish, Estonian, Persian, Finnish, Filipino, French, Irish, Hebrew, Hindi, Croatian, Hungarian, Indonesian, Icelandic, Italian, Japanese, Korean, Lithuanian, Latvian, Malay, Maltese, Dutch, Norwegian, Punjabi, Polish, Portuguese, Romanian, Russian, Slovak, Slovenian, Serbian, Swedish, Tamil, Telugu, Thai, Turkish, Ukrainian, Urdu, Vietnamese, Chinese.
License : Apache 2.0 Availability Command A+ ( command-a-plus-05-2026 ) is now available for all Cohere users through our standard API endpoints.
For enterprise customers, private deployment options are available to ensure maximum security and control over your translation workflows.
For more detailed information about Command A+, including technical specifications and implementation examples, visit our model documentation .
April 4, 2026 April 4, 2026 Retirement of Embed v2.0 and Aya Expanse / Vision 8B Retirement notice Effective April 4, 2026, the following models are no longer available.
Requests using these model IDs will fail.
Retired models: embed-english-v2.0 embed-english-light-v2.0 embed-multilingual-v2.0 c4ai-aya-expanse-8b c4ai-aya-vision-8b We recommend these replacements: Embedding tasks embed-english-v3.0 embed-multilingual-v3.0 embed-v4.0 Chat tasks command-r7b-12-2024 command-a-03-2025 command-a-reasoning-08-2025 For the full announcement and lifecycle context, see the Deprecations page.
For questions or assistance, contact support@cohere.com .
Older posts Next Built with Guides and concepts API Reference Release Notes LLMU Cookbooks v2 API v1 API
