API Key Security Notice: Rotate Keys and Restrict Network Access - Documentation Documentation Index Fetch the complete documentation index at: /llms.txt Use this file to discover all available pages before exploring further.
Skip to main content Assistant Responses are generated using AI and may contain mistakes.
Contact support Documentation home page Guides API Reference Changelog Go to Console Go to Console Search...
Navigation Changelog API Key Security Notice: Rotate Keys and Restrict Network Access Search...
⌘ K Changelog Nov 3, 2026 API Key Security Notice Nov 2, 2026 Sandbox Upgrade Notice Oct 28, 2026 New Sandbox Console Oct 23, 2026 Model Deprecation Oct 26, 2026 GPUs Access Authentication Upgrade Oct 29, 2026 Model Deprecation Oct 9, 2026 Model Deprecation Sep 23, 2026 Sandbox Agent Skills Update Sep 29 & Oct 9, 2026 Model Deprecations Sep 18, 2026 Sandbox Upgrade Notice Sep 8, 2026 Sandbox Upgrade Notice Sep 30, 2026 Model Deprecations Aug 28, 2026 Updates Aug 14, 2026 Updates Aug 12, 2026 Updates Aug 11, 2026 Updates Aug 3, 2026 Updates Jul 7, 2026 Updates Jun 25, 2026 Updates Jun 23, 2026
Updates Jun 22, 2026 Updates Jun 17, 2026 Updates Sandbox SDK / CLI Upgrade Notice Sandbox SDK / CLI Upgrade Advance Notice LLM Serverless Model Deprecation Notice LLM Serverless Model Deprecation Notice May 25, 2026 LLM Serverless Model Deprecation Notice April 17, 2026 LLM API Billing Rules Explained GPU Pricing Update Notice January 19, 2026 Product Updates LLM Serverless Model Deprecation Notice Nov 11, 2025 Updates Nov 3, 2025 Updates September 28, 2025 Updates September 19, 2025 Updates September 12, 2025 Updates September 5, 2025 Updates August 29, 2025 Updates August 22, 2025 Updates
August 15, 2025 Updates August 8, 2025 Updates August 1, 2025 Updates July 31, 2025 Updates July 25, 2025 Updates July 18, 2025 Updates July 11, 2025 Updates July 4, 2025 Updates July 03, 2025 Notice June 20, 2025 Updates June 6, 2025 Updates May 30, 2025 Updates May 23, 2025 Updates May 16, 2025 Updates May 14, 2025 Notice April 30, 2025 Updates April 30, 2025 Updates April 25, 2025 Updates April 18, 2025 Updates April 11, 2025 Updates April 04, 2025 Updates March 28, 2025 Updates March 26, 2025 Notice March 21, 2025 Updates March 14, 2025 Updates February 14, 2025 February 6, 2025 January
24, 2025 January 22, 2025 January 16, 2025 January 9, 2025 December 26, 2024 December 19, 2024 December 7, 2024 November 27, 2024 November 11, 2024 October 19, 2024 September 6, 2024 July 24, 2024 July 19, 2024 June 2, 2024 May 28, 2024 May 9, 2024 April 29, 2024 April 19, 2024 April 11, 2024 April 7, 2024 March 20, 2024 March 14, 2024 February 29, 2024 English On this page Back to top How to rotate an API key Changelog API Key Security Notice: Rotate Keys and Restrict Network Access Copy page Copy page Novita recommends rotating API keys regularly and configuring network access policies to
reduce the risk of key exposure or misuse.
Copy page Copy page To keep your account and services secure, and to reduce the risk of API keys being accidentally exposed or misused during storage, configuration, and use, we recommend that you review your key usage regularly and take the following measures: Store API keys securely.
Do not put API keys directly in startup commands, commit them to code repositories, or write them to logs.
Do not show full keys in public documents, screenshots, or other shared content.
Use a separate API key for each environment and service instead of sharing one key, so each key can be rotated or disabled on its own.
Configure a network access policy for your API keys so that only trusted sources can use them.
See Network Access for API Keys .
Rotate the API keys you use regularly, and delete keys you no longer need.
​ How to rotate an API key Go to Key Management in the console and create a new API key.
Replace the old key with the new one in your applications and services, and verify that calls succeed.
After confirming that every application and service that used the old key has been updated, delete the old key.
If you suspect an API key has been leaked, delete it immediately, then create and configure a new key.
Applications and services still using the deleted key will no longer be able to make calls, so update their configuration at the same time.
If you need help, feel free to contact us.
Thank you for your understanding and cooperation.
Released on November 3, 2026 (UTC).
Last modified on November 3, 2026 Sandbox Upgrade Notice Next ⌘ I Documentation home page discord github x Community Discord Support Resources Pricing Models Agent Skill Company Novita AI Console discord github x Powered by This documentation is built and hosted on Mintlify, a developer documentation platform
