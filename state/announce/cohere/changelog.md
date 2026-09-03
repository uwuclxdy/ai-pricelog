Release Notes | Cohere For AI agents: a documentation index is available at the root level at /llms.txt.
Append /llms.txt to any URL for a page-level index, or .md for the markdown version of any page.
docs v2 API v2 API Search / Ask AI DASHBOARD PLAYGROUND DOCS COMMUNITY LOG IN Guides and concepts API Reference Release Notes LLMU Cookbooks Search / Ask AI v2 API v2 API Guides and concepts API Reference Release Notes LLMU Cookbooks DASHBOARD PLAYGROUND DOCS COMMUNITY LOG IN Light On this page August 27, 2026 Availability July 7, 2026 Technical Details Availability June 9, 2026 Technical Details Availability May 20, 2026 Key Features Technical Details Availability April 4, 2026 Retirement notice March 26, 2026 Technical details Getting started Availability December 11, 2025 Technical Details
Example Query August 28, 2025 Key Features Getting Started Availability August 21, 2025 Getting Started Release Notes Subscribe via RSS August 27, 2026 August 27, 2026 July 7, 2026 July 7, 2026 June 9, 2026 June 9, 2026 May 20, 2026 May 20, 2026 April 4, 2026 April 4, 2026 March 26, 2026 March 26, 2026 December 11, 2025 December 11, 2025 September 16, 2025 September 16, 2025 August 28, 2025 August 28, 2025 August 21, 2025 August 21, 2025 Older posts Next Built with Meet Cohere Parse Today we are releasing Cohere Parse .
Parse (model ID: parse-v5.0 ) turns complex documents into clean, structured Markdown ready for downstream AI workflows.
The 2.3B-parameter multimodal model extracts text in reading order, tables, lists, forms, images and captions, page boundaries, and visual element locations.
Outputs include Markdown/HTML content, HTML-formatted tables, bounding boxes, and image descriptions — preserving both document structure and layout for easier rendering and processing.
Key specs: 8K context window · ~4.6GB model size · Markdown output Availability Cohere Parse is available through the Parse API, as well as Microsoft Foundry and AWS SageMaker .
For single-tenant deployment, Parse is also available in Model Vault .
For more details, see the model documentation .
Meet Cohere Transcribe Arabic Today we are releasing Cohere Transcribe Arabic .
This open-source speech-to-text model is a fine-tune of Cohere Transcribe using Arabic speech data.
It lets Arabic speakers transcribe their voice with unmatched accuracy and support for regional dialects or speech patterns.
It is currently the most accurate open-source Arabic ASR model available today and is optimized for production inference and throughput.
Technical Details Model Name : cohere-transcribe-arabic-07-2026 Size : 2B Architecture : conformer-based encoder-decoder Languages supported : Arabic (all major dialects), English (including English spoken with an Arabic accent) License : Apache 2.0 Availability Cohere Transcribe Arabic is available through the V2 Audio Transcriptions API and as open weights on Hugging Face .
For production use, Model Vault deployment is also supported.
For more details, see the model documentation .
Announcing Cohere's North Mini Code We’re pleased to announce the release of North Mini Code , Cohere’s first agentic coding model.
It is a 30 billion total / 3 billion active parameter Mixture of Experts model trained specifically for agentic coding, with a small enough active footprint to run on local hardware.
Technical Details Model Name : north-mini-code-1-0 Context Length : 256K input, 64K output License : Apache 2.0 Availability North Mini Code is available through the Chat V2 API and as open weights on Hugging Face.
For production use, Model Vault deployment is also supported.
For more details, see the model documentation .
Announcing Cohere’s Command A+ We’re pleased to announce the release of Command A+ , the last model in the Command A family of models, combining support for vision inputs, reasoning capabilities, translation capabilities, and agentic tasks all within the same model.
It is also notably our first Mixture of Experts (MoE) model with 25 billion active parameters ands 218 billion total parameters.
Key Features Agentic Applications : With notable performance increases in tool use and agentic tasks, Command A+ is the strongest agentic model in the Command family.
Expanded Multilingual Support : With 48 languages supported, including all official EU languages, this more than doubles the support of languages from our prior models.
Efficient & Fast : With as few as 1 x B200 or 2 x H100s required to deploy the model, and up to 110% throughput increase and 30% decrease in latency over Command A Reasoning, the model is designed for production-grade deployments.
Technical Details Model Name : command-a-plus-05-2026 Context Length : 128K input, 64K output Languages covered : English, Arabic, Bulgarian, Bengali, Catalan, Czech, Danish, German, Greek, Spanish, Estonian, Persian, Finnish, Filipino, French, Irish, Hebrew, Hindi, Croatian, Hungarian, Indonesian, Icelandic, Italian, Japanese, Korean, Lithuanian, Latvian, Malay, Maltese, Dutch, Norwegian, Punjabi, Polish, Portuguese, Romanian, Russian, Slovak, Slovenian, Serbian, Swedish, Tamil, Telugu, Thai, Turkish, Ukrainian, Urdu, Vietnamese, Chinese.
License : Apache 2.0 Availability Command A+ ( command-a-plus-05-2026 ) is now available for all Cohere users through our standard API endpoints.
For enterprise customers, private deployment options are available to ensure maximum security and control over your translation workflows.
For more detailed information about Command A+, including technical specifications and implementation examples, visit our model documentation .
Retirement of Embed v2.0 and Aya Expanse / Vision 8B Retirement notice Effective April 4, 2026, the following models are no longer available.
Requests using these model IDs will fail.
Retired models: embed-english-v2.0 embed-english-light-v2.0 embed-multilingual-v2.0 c4ai-aya-expanse-8b c4ai-aya-vision-8b We recommend these replacements: Embedding tasks embed-english-v3.0 embed-multilingual-v3.0 embed-v4.0 Chat tasks command-r7b-12-2024 command-a-03-2025 command-a-reasoning-08-2025 For the full announcement and lifecycle context, see the Deprecations page.
For questions or assistance, contact support@cohere.com .
Announcing the Cohere Transcribe model We’re pleased to announce the release of Cohere Transcribe , our first transcription model.
Cohere Transcribe specializes in audio-in, text-out, automatic speech recognition (ASR).
Technical details Model name : cohere-transcribe-03-2026 Input : Audio waveform Output : Text Languages covered : English, German, French, Italian, Spanish, Portuguese, Greek, Dutch, Polish, Vietnamese, Chinese, Arabic, Japanese, Korean.
License : Apache 2.0 API endpoint : Audio Transcriptions API Getting started The model is available immediately through Cohere’s Audio Transcriptions API endpoint .
You can start transcribing audio using the following example query: PYTHON 1 import cohere 2 3 co = cohere .
ClientV2 () 4 5 response = co .
audio .
transcriptions .
create ( 6 model = " cohere-transcribe-03-2026 " , 7 language = " en " , 8 file = open ( " ./sample.wav " , " rb " ), 9 ) 10 11 print ( response ) Availability You can access Cohere Transcribe via our API for free, low-setup experimentation subject to rate limits.
See the Different Types of API Keys and Rate Limits page for usage details and integration guidance.
For production deployment without rate limits, provision a dedicated Model Vault .
This enables low-latency, private cloud inference without having to manage infrastructure.
Pricing is calculated per hour-instance, with discounted plans for longer-term commitments.
Contact our team to discuss your requirements.
Cohere's Rerank v4.0 Model is Here!
We’re pleased to announce the release of Rerank 4.0 our newest and most performant foundational model for ranking.
Technical Details Two model variants available: rerank-v4.0-pro : Optimized for state-of-the-art quality and complex use-cases rerank-v4.0-fast : Optimized for low latency and high throughput use-cases Multilingual support : Re-rank both English and non-English documents Semi-structured data support : Re-rank JSON documents Extended context length : 32k token context window Example Query PYTHON 1 import cohere 2 3 co = cohere .
ClientV2 () 4 5 query = " What is the capital of the United States?
" 6 docs = [ 7 " Carson City is the capital city of the American state of Nevada.
At the 2010 United States Census, Carson City had a population of 55,274.
" , 8 " The Commonwealth of the Northern Mariana Islands is a group of islands in the Pacific Ocean that are a political division controlled by the United States.
Its capital is Saipan.
" , 9 " Charlotte Amalie is the capital and largest city of the United States Virgin Islands.
It has about 20,000 people.
The city is on the island of Saint Thomas.
" , 10 " Washington, D.C.
(also known as simply Washington or D.C., and officially as the District of Columbia) is the capital of the United States.
It is a federal district.
The President of the USA and many major national government offices are in the territory.
This makes it the political center of the United States of America.
" , 11 " Capital punishment has existed in the United States since before the United States was a country.
As of 2017, capital punishment is legal in 30 of the 50 states.
The federal government (including the United States military) also uses capital punishment.
" , 12 ] 13 14 results = co .
rerank ( 15 model = " rerank-v4.0-pro " , query = query , documents = docs , top_n = 5 16 ) Announcing Major Command Deprecations As part of our ongoing commitment to delivering advanced AI solutions, we are deprecating the following models, features, and API endpoints: Deprecated Models: command-r-03-2024 (and the alias command-r ) command-r-plus-04-2024 (and the alias command-r-plus ) command-light command summarize (Refer to the migration guide for alternatives).
For command model replacements, we recommend you use command-r-08-2024 , command-r-plus-08-2024 , or command-a-03-2025 (which is the strongest-performing model across domains) instead.
Retired Fine-Tuning Capabilities: All fine-tuning options via dashboard and API for models including command-light , command , command-r , classify , and rerank are being retired.
Previously fine-tuned models will no longer be accessible.
Deprecated Features and API Endpoints: /v1/connectors (Managed connectors for RAG) /v1/chat parameters: connectors , search_queries_only /v1/generate (Legacy generative endpoint) /v1/summarize (Legacy summarization endpoint) /v1/classify Slack App integration Coral Web UI (chat.cohere.com and coral.cohere.com) For questions, reach out to support@cohere.com Announcing Cohere's Command A Translate Model We’re excited to announce the release of Command A Translate , Cohere’s first machine translation model.
It achieves state-of-the-art performance at producing accurate, fluent translations across 23 languages.
Key Features 23 supported languages : English, French, Spanish, Italian, German, Portuguese, Japanese, Korean, Chinese, Arabic, Russian, Polish, Turkish, Vietnamese, Dutch, Czech, Indonesian, Ukrainian, Romanian, Greek, Hindi, Hebrew, and Persian 111 billion parameters for superior translation quality 16K token context length (8K input + 8K output) for handling longer texts Optimized for deployment on 1-2 GPUs (A100s/H100s) Secure deployment options for sensitive data translation Getting Started The model is available immediately through Cohere’s Chat API endpoint.
You can start translating text with simple prompts or integrate it programmatically into your applications.
1 from cohere import ClientV2 2 3 co = ClientV2 ( api_key = " <YOUR API KEY> " ) 4 5 response = co .
chat ( 6 model = " command-a-translate-08-2025 " , 7 messages = [ 8 { 9 " role " : " user " , 10 " content " : " Translate this text to Spanish: Hello, how are you?
" , 11 } 12 ], 13 ) Availability Command A Translate ( command-a-translate-08-2025 ) is now available for all Cohere users through our standard API endpoints.
For enterprise customers, private deployment options are available to ensure maximum security and control over your translation workflows.
For more detailed information about Command A Translate, including technical specifications and implementation examples, visit our model documentation .
Announcing Cohere's Command A Reasoning Model We’re excited to announce the release of Command A Reasoning , a hybrid reasoning model designed to excel at complex agentic tasks, in English and 22 other languages.
With 111 billion parameters and a 256K context length, this model brings advanced reasoning capabilities to your applications through the familiar Command API interface.
Key Features Tool Use : Provides the strongest tool use performance out of the Command family of models.
Agentic Applications : Demonstrates proactive problem-solving, autonomously using tools and resources to complete highly complex tasks.
Multilingual : With 23 languages supported, the model solves reasoning and agentic problems in the language your business operates in.
Technical Specifications Model Name : command-a-reasoning-08-2025 Context Length : 256K tokens Maximum Output : 32K tokens API Endpoint : Chat API Getting Started Integrating Command A Reasoning is straightforward using the Chat API.
Here’s a non-streaming example: PYTHON PYTHON (Streaming) 1 from cohere import ClientV2 2 3 co = ClientV2 ( " <YOUR_API_KEY> " ) 4 5 prompt = """ 6 Alice has 3 brothers and she also has 2 sisters.
How many sisters does Alice's brother have?
7 """ 8 9 response = co .
chat ( 10 model = " command-a-reasoning-08-2025 " , 11 messages = [ 12 { 13 " role " : " user " , 14 " content " : prompt , 15 } 16 ], 17 ) 18 19 for content in response .
message .
content : 20 if content .
type == " thinking " : 21 print ( " Thinking: " , content .
thinking ) 22 23 if content .
type == " text " : 24 print ( " Response: " , content .
text ) Customization Options You can enable and disable thinking capabilities using the thinking parameter, and steer the model’s output with a flexible user-controlled thinking budget; for more details on token budgets, advanced configurations, and best practices, refer to our dedicated Reasoning documentation .
