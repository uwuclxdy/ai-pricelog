Novita GPUs Access Authentication Upgrade - Documentation Documentation Index Fetch the complete documentation index at: /llms.txt Use this file to discover all available pages before exploring further.
Skip to main content Documentation home page Guides API Reference Changelog Go to Console Go to Console Search...
Navigation Changelog Novita GPUs Access Authentication Upgrade Search...
⌘ K Changelog Oct 26, 2026 GPUs Access Authentication Upgrade Oct 29, 2026 Model Deprecation Oct 9, 2026 Model Deprecation Sep 23, 2026 Sandbox Agent Skills Update Sep 29 & Oct 9, 2026 Model Deprecations Sep 18, 2026 Sandbox Upgrade Notice Sep 8, 2026 Sandbox Upgrade Notice Sep 30, 2026 Model Deprecations Aug 28, 2026 Updates Aug 14, 2026 Updates Aug 12, 2026 Updates Aug 11, 2026 Updates Aug 3, 2026 Updates Jul 7, 2026 Updates Jun 25, 2026 Updates Jun 23, 2026 Updates Jun 22, 2026 Updates Jun 17, 2026 Updates Sandbox SDK / CLI Upgrade Notice Sandbox SDK / CLI Upgrade Advance Notice LLM
Serverless Model Deprecation Notice LLM Serverless Model Deprecation Notice May 25, 2026 LLM Serverless Model Deprecation Notice April 17, 2026 LLM API Billing Rules Explained GPU Pricing Update Notice January 19, 2026 Product Updates LLM Serverless Model Deprecation Notice Nov 11, 2025 Updates Nov 3, 2025 Updates September 28, 2025 Updates September 19, 2025 Updates September 12, 2025 Updates September 5, 2025 Updates August 29, 2025 Updates August 22, 2025 Updates August 15, 2025 Updates August 8, 2025 Updates August 1, 2025 Updates July 31, 2025 Updates July 25, 2025 Updates July 18, 2025
Updates July 11, 2025 Updates July 4, 2025 Updates July 03, 2025 Notice June 20, 2025 Updates June 6, 2025 Updates May 30, 2025 Updates May 23, 2025 Updates May 16, 2025 Updates May 14, 2025 Notice April 30, 2025 Updates April 30, 2025 Updates April 25, 2025 Updates April 18, 2025 Updates April 11, 2025 Updates April 04, 2025 Updates March 28, 2025 Updates March 26, 2025 Notice March 21, 2025 Updates March 14, 2025 Updates February 14, 2025 February 6, 2025 January 24, 2025 January 22, 2025 January 16, 2025 January 9, 2025 December 26, 2024 December 19, 2024 December 7, 2024 November 27, 2024
November 11, 2024 October 19, 2024 September 6, 2024 July 24, 2024 July 19, 2024 June 2, 2024 May 28, 2024 May 9, 2024 April 29, 2024 April 19, 2024 April 11, 2024 April 7, 2024 March 20, 2024 March 14, 2024 February 29, 2024 English On this page What changes How to adapt Transition period Changelog Novita GPUs Access Authentication Upgrade Copy page Copy page Copy page Copy page To protect the platform and your workloads, Novita AI is upgrading access authentication for the GPUs product line (Serverless and GPU Instance).
Starting October 26, 2026 (UTC) , requests that reach these services through Novita’s default domains must carry a valid API key, or originate from a whitelisted source IP.
Unauthenticated public access will no longer be supported.
​ What changes Serverless : Endpoint calls must include a valid API key.
Unauthenticated requests return HTTP 401.
GPU Instance HTTP port mapping : Requests to instance HTTP services through *.gpu-instance.novita.ai must include a valid API key.
GPU Instance TCP port mapping : SSH, database, and other TCP services require a source IP whitelist.
TCP port mapping is no longer open to the internet.
If you use TCP port mapping, submit your whitelist before October 26, 2026.
​ How to adapt Add a standard Bearer token header to every request, using your Novita API key: Authorization: Bearer {api-key} The hosts stay the same as today.
Callers only need the extra header.
Access path Host Serverless Endpoint *.runsync.novita.dev GPU Instance HTTP port mapping *.gpu-instance.novita.ai GPU Instance TCP port mapping proxy.{region}.gpu-instance.novita.ai — requires a source IP whitelist instead of an API key If you have shared your endpoint URL with third parties, or embedded it in frontend or mobile code, update those callers and redeploy.
Manage API keys: https://novita.ai/settings/key-management API key documentation: /guides/llm-api-keys For TCP port mapping, submit your source IP whitelist through customer support.
​ Transition period October 19 to October 26, 2026 is the transition period.
Existing access methods keep working during this window.
Please complete your changes as early as possible to avoid service interruption.
Last modified on October 20, 2026 Oct 29, 2026 Model Deprecation Notice Next ⌘ I Documentation home page discord github x Community Discord Support Resources Pricing Models Agent Skill Company Novita AI Console discord github x Powered by This documentation is built and hosted on Mintlify, a developer documentation platform Assistant Responses are generated using AI and may contain mistakes.
Contact support
