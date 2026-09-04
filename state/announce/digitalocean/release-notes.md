Release Notes | DigitalOcean Documentation Docs Platform Products Reference Support Sign Up Release Notes Regional Availability Accounts Teams Organizations Billing AI Assistant public Support DDoS Protection Product Lifecycle Stages Resource Limits Service-Level Agreements Security on DigitalOcean DigitalOcean IP ranges (CSV) Release Notes Give Feedback For AI agents: The documentation index is at https://docs.digitalocean.com/llms.txt .
Markdown versions of pages use the same URL with index.html.md in place of the HTML page (for example, append index.html.md to the directory path instead of opening the HTML document).
Release Notes Last verified 30 Jul 2026 Copy page as Markdown View page as Markdown Release notes track incremental improvements and major releases for the DigitalOcean cloud platform.
This page lists notes from the last 90 days .
For AI tools, prefer Recent Release Notes ( /release-notes/recent/ or JSON ).
For the full history, see the release notes archive .
You can subscribe to the release notes RSS feed .
Due to the high frequency of its updates, we keep a separate changelog for Kubernetes version updates September 2026 1 September DigitalOcean Kubernetes (DOKS) now supports Isolated Worker Nodes in public preview .
Every worker node in an isolated cluster runs without a public IPv4 address, so nodes are removed from the public internet at the network level rather than only protected by a firewall.
Outbound traffic, including node provisioning and container image pulls, routes through a VPC NAT Gateway, and other resources in the same VPC reach the nodes over private addresses.
The Kubernetes API server stays publicly reachable so you can still manage the cluster.
You enable isolation when you create a cluster running Kubernetes 1.36 or later.
The peer-to-peer OCI registry plugin for DigitalOcean Kubernetes (DOKS) is now in general availability .
The plugin uses Spegel to mirror container image layers across cluster nodes, so a node can pull layers from a peer that already has them instead of the origin registry.
This reduces the number of pulls that leave the cluster, lowers your exposure to external registries’ rate limits, and speeds up image pulls on clusters that reuse the same images across many nodes.
The plugin is disabled by default and is available on clusters running Kubernetes 1.36 or later.
The following Anthropic model is now available on DigitalOcean Inference for serverless inference , Agent Development Kit , and agents : Claude Fable 5.1 For more information, see the Available Models page .
August 2026 28 August The following Z.ai model is now available on DigitalOcean Inference for serverless inference , Agent Development Kit , and agents : GLM-5.3 For more information, see the Available Models page .
27 August The following Z.ai model is now available on DigitalOcean Inference for serverless inference , Agent Development Kit , and agents : GLM-5.3 Flash For more information, see the Available Models page .
25 August v5 Droplet configurations are now available in the atl1 , ric1 , mkc1 , and mem1 datacenters.
They run on 5th Generation AMD EPYC processors for higher per-core performance and let you size compute, memory, storage, and networking independently.
Choose Shared for shared vCPUs or General Purpose for dedicated vCPUs.
v5 Droplets are billed per second at an hourly rate without a monthly usage cap.
DigitalOcean Kubernetes (DOKS) supports a subset of v5 configurations in these datacenters, with 50 GiB or 80 GiB boot disks.
For details, see How to Create a Droplet , Choosing the Right CPU Droplet Plan , and Choosing the Right Kubernetes Plan .
24 August Updated NVIDIA AI/ML Ready ( gpu-h100x1-base , gpu-h100x8-base ) Droplet base images are now available in the Control Panel and through the API.
The images are based on Ubuntu 24.04 (upgraded from Ubuntu 22.04) and include NVIDIA driver 580.173.02 and CUDA 13.1, providing the latest NVIDIA GPU support for AI/ML workloads.
Despite their slug names, these images are compatible with all NVIDIA GPU Droplet types we offer.
For more information, see Recommended Drivers and Software for GPU Droplets .
20 August Qwen3.8-2.4T-A95B model available on DigitalOcean Inference has been upgraded to Qwen3.8-Max .
Qwen3.8-Max supports vision and video input and a 1M-token context window.
For more information, see the Available Models page .
19 August Inference Router now uses cache-aware routing to maximize prompt cache reuse and automatically applies prompt caching to eligible Anthropic requests.
You can opt out of prompt caching for supported models with X-Model-Affinity: none and control cache-aware model switching with the x-routing-max-switch-spend-pct header.
For more information, see Use Prompt Caching .
18 August The following open-source models are deprecated from DigitalOcean Inference as of 18 August 2026: Llama 3.3 Instruct-70B DeepSeek R1 Distill Llama 70B Qwen3-32B Qwen3 Coder Flash Migrate Llama 3.3 Instruct-70B to Llama 4 Maverick 17B 128E Instruct ( llama-4-maverick ), DeepSeek R1 Distill Llama 70B to DeepSeek V4 Flash ( deepseek-4-flash ), and Qwen3-32B and Qwen3 Coder Flash to Qwen 3.5 397B A17B ( qwen3.5-397b-a17b ) to avoid service disruption.
For information on our model deprecation policy and recommended replacement models, see Model Support Policy .
14 August The following DeepSeek model is now available on DigitalOcean Inference for serverless inference , Agent Development Kit , and agents : DeepSeek V4 Pro 0813 For more information, see the Available Models page .
13 August DigitalOcean Kubernetes (DOKS) now supports Dynamic Resource Allocation (DRA) drivers for NVIDIA and AMD GPU node pools in public preview , starting with DOKS 1.36.3-do.0 .
DRA is an opt-in alternative to the managed GPU device plugins.
Workloads that already request GPUs with extended resources such as nvidia.com/gpu or amd.com/gpu continue to work without changes after switching to DRA.
12 August The following Alibaba model is now available on DigitalOcean Inference for serverless inference , Agent Development Kit , and agents : Qwen3.8-2.4T-A95B For more information, see the Available Models page .
Cloud Security Posture Management (CSPM) paid plans support Managed Rules, which let you enable or disable CSPM rules for your entire team.
To exclude specific resources while keeping a rule enabled for the rest of the team, suppress findings for those resources.
For more information, see How to Manage Rules and How to Suppress Findings .
10 August We have launched the Memphis, Tennessee, USA ( mem1 ) datacenter, which supports AMD Instinct MI355X Spot GPU Droplets and many other products.
For the full list of supported products, see the regional availability matrix .
AMD Instinct MI355X GPUs are now available in MEM1 as Spot GPU Droplets in 1- and 8-GPU configurations.
Spot prices vary daily based on available capacity.
For pricing, see Spot GPU Droplet pricing .
Spot GPU Droplets are now available in public preview for supported GPUs in single-GPU and 8-GPU configurations.
Pricing may change daily based on capacity.
To compare the capacity tiers, see Spot GPU Droplets vs On-Demand GPU Droplets .
DigitalOcean Container Registry (DOCR) now provides mirror registries: DigitalOcean-curated regional mirrors of popular AI container images, available in 11 datacenter regions.
You can pull nvidia/pytorch and rocm/pytorch images from a region-local mirror using standard Docker tooling, or use SOCI lazy loading to start containers in seconds while image layers stream on demand.
DOCR also supports pushing your own SOCI-enabled images to your registry.
For details, see How to Pull AI Images from DOCR Mirror Registries and How to Push SOCI-Enabled Images to Your Container Registry .
6 August The following DeepSeek model is now available on DigitalOcean Inference for serverless inference , Agent Development Kit , and agents : DeepSeek V4 Flash 0731 For more information, see the Available Models page .
DigitalOcean has patched “Safe RET” across our AMD Droplet fleet.
We applied the fix at the infrastructure level, and no customer action is required.
For more information, see AMD’s security bulletin, AMD-SB-7061 .
5 August Spend alerts are now generally available for teams and organizations, replacing billing alerts.
You can create multiple alerts with incremental percentage thresholds, scoped to total spend, specific products, or, for organizations, specific teams.
Notifications arrive within an hour of your spend crossing a threshold.
Existing billing alerts have been migrated to the Spend alerts page as an alert named Account Spend Alert .
The following Anthropic model is deprecated from DigitalOcean Inference as of 5 August 2026: Claude Opus 4.1 Migrate to Claude Opus 4.8 ( anthropic-claude-opus-4.8 ) to avoid service disruption.
For information on our model deprecation policy and recommended replacement models, see Model Support Policy .
4 August We have launched the Kansas City, Missouri, USA ( mkc1 ) datacenter, which supports GPU Droplets, Kubernetes, Managed Databases, Spaces object storage, App Platform, Functions, and many other products.
For the full list of supported products, see the regional availability matrix .
Cloud firewall rules now support an action of allow or deny.
Deny rules let you block traffic from specific sources, such as known malicious IP addresses, while allowing broader access to your services.
Deny rules take precedence over allow rules that match the same traffic.
For rule actions and configuration steps, see How to Configure Firewall Rules .
3 August PostgreSQL Advanced Edition clusters now support sslmode=verify-full for full TLS certificate verification.
For setup, see How to Connect to PostgreSQL Database Clusters and Increase TLS Verification with sslmode .
July 2026 30 July OpenSearch 3.3 and 3.6 are now available for database clusters .
New clusters use OpenSearch 2.19 by default.
Kafka versions 3.9 and 4.1 are now available for database clusters .
New clusters use Kafka 4.1 by default.
For version support and Kafka 3.8 end of availability, see Kafka Limits .
28 July DigitalOcean Kubernetes (DOKS) now includes an optional peer-to-peer OCI registry plugin in public preview .
The plugin uses Spegel to mirror container image layers across cluster nodes, so a node can pull layers from a peer that already has them instead of the origin registry.
This reduces the number of pulls that leave the cluster, lowers your exposure to external registries’ rate limits, and speeds up image pulls on clusters that reuse the same images across many nodes.
The plugin is disabled by default and is available on new clusters running Kubernetes 1.36 or later.
27 July The following Moonshot AI model is now available on DigitalOcean Inference for serverless inference , dedicated inference , Agent Development Kit , and agents : Kimi K3 For more information, see the Available Models page .
24 July The following Anthropic model is now available on DigitalOcean Inference for serverless inference , Agent Development Kit , and agents : Claude Opus 5 For more information, see the Available Models page .
23 July The following OpenAI model is deprecated from DigitalOcean Inference as of 23 July 2026: GPT-5.1-Codex-Max Migrate to GPT-5.3-Codex ( openai-gpt-5.3-codex ) to avoid service disruption.
For information on our model deprecation policy and recommended replacement models, see Model Support Policy .
We now support prompt caching for Gemma 4 for serverless inference.
The server-side model synthesis tool is available in public preview on DigitalOcean Inference.
The model synthesis tool is an API-only multi-model tool that runs up to eight analysis models in parallel on the same task, compares their results, and returns one synthesized answer.
You can use the model synthesis tool with serverless inference, dedicated inference, and inference routers on the Chat Completions, Responses, and Messages APIs.
Opt in from the Feature Preview page .
For more information, see How to Use the Model Synthesis Tool .
Released v1.164.0 of doctl , the official DigitalOcean CLI.
This release adds commands for managing Secrets Manager secrets and Network File Storage access points.
We have updated the following buildpack for App Platform: Node.js buildpack : We added the following Node.js versions and updated the buildpack to version 342 .
Visit the Node.js buildpack to learn more about specifying a Node.js engine version.
Node.js 24.15.0 15 July Managed databases are available in Kansas City ( mkc1 ) with limited plan availability.
Premium AMD plans and General Purpose MongoDB clusters are not available in this region.
See the regional availability matrix for current coverage by engine.
The Gradient AI Go Library is deprecated.
Use the official DigitalOcean Go SDK (Godo) or the DigitalOcean API directly.
For installation and quickstart examples, see SDK and Client Libraries .
The Gradient AI Python SDK is deprecated.
Use the official DigitalOcean Python SDK (PyDo) or the DigitalOcean API directly.
For installation and quickstart examples, see SDK and Client Libraries .
The Gradient AI TypeScript SDK is deprecated.
Use the official DigitalOcean TypeScript SDK (DoTs) or the DigitalOcean API directly.
For installation and quickstart examples, see SDK and Client Libraries .
10 July PostgreSQL Standard Edition clusters now support sslmode=verify-full for full TLS certificate verification.
For setup, see How to Connect to PostgreSQL Database Clusters and Increase TLS Verification with sslmode .
The following OpenAI models are now available on DigitalOcean Inference for serverless inference : GPT-5.6 Sol GPT-5.6 Terra GPT-5.6 Luna For more information, see the Available Models page .
9 July Ubuntu 25.10 has reached end of life.
Per our image deprecation policy , this image is available exclusively via the API for the next 30 days before we remove it from our platform.
8 July DigitalOcean Kubernetes (DOKS) now supports automatic node remediation in public preview .
DOKS can automatically replace worker nodes that stay unhealthy, based on Kubernetes node conditions and rules you define.
The Data Plane Operator runs in your cluster, watches node conditions, and replaces a worker when a condition matches your rules for a configured duration.
You can act on standard kubelet conditions, such as Ready , and on custom conditions you publish from your own health checks.
You configure remediation by deploying the DataPlaneOperatorConfig and NodeRemediationConfig custom resources to your cluster.
2 July DigitalOcean Kubernetes (DOKS) now runs a node readiness controller in public preview .
The controller watches node conditions and holds NoSchedule taints on nodes until required components, including GPU drivers on GPU nodes, report healthy, which prevents pods from scheduling onto nodes that are not yet ready.
DOKS deploys and manages the controller automatically.
For GPU node pools, you can also customize which GPU health metrics gate scheduling, without redeploying any components.
1 July DigitalOcean Managed Weaviate is now in public preview and enabled for all users.
Weaviate is a fully managed vector database for retrieval-augmented generation and semantic search workloads.
Create clusters from the Vector Databases page , the /v2/vector-databases API , or doctl vector-databases .
Select Weaviate as the engine and review the public preview disclaimer and legal terms in the create flow.
For setup, limits, and pricing, see Managed Weaviate .
Claude Fable 5 is available again on DigitalOcean Inference for serverless inference , Agent Development Kit , and agents .
For more information, see the Available Models page .
Prompt caching for open-source models in serverless inference chat completions and responses API is now in public preview .
Open-source models cache context automatically, so you do not need to set the cache_control or prompt_cache_retention parameters.
Prompt caching is available for the following open-source models: DeepSeek V3.2 DeepSeek V4 Pro DeepSeek V4 Flash Kimi K2.5 Kimi K2.6 GLM 5 GLM-5.1 GLM-5.2 gpt-oss-120b MiMo V2.5 MiMo V2.5 Pro MiniMax M2.5 Qwen 3.5 Qwen3 Coder Flash For more information, see Use Prompt Caching .
The Ubuntu 26.04 LTS ( ubuntu-26-04-x64 ) base image is now available in the control panel and via the API.
Invoice and Billing Insights CSV files now include a tag_name column that lists the tags applied to each resource.
Tag information is included only for resource usage on or after 1 July 2026.
June 2026 30 June DigitalOcean Managed Valkey database clusters now support custom CNAME records, allowing clients to connect through your own hostname instead of the default *.db.ondigitalocean.com address.
Custom CNAMEs are available through the API when creating clusters or when updating an existing cluster, and apply to the public network connection only.
For more information, see Configure Custom CNAMEs for Valkey .
Private Droplets are now generally available in all regions.
Private Droplets have no public network interface and no public IP address, using VPC-only networking with automatic integration with VPC NAT gateway, VPC peering, and VPC private DNS.
See the Private Droplets documentation for setup instructions and limitations.
The following agent evaluation metrics are deprecated and should no longer be used: Tone Retrieved Chunk Usage Prompt Perplexity Use the currently supported metrics listed in Agent Evaluation Metrics instead.
To monitor deployed agent behavior outside of evaluations, use Agent Metrics and Runtime Logs .
The following Anthropic model is now available on DigitalOcean Inference for serverless inference , Agent Development Kit , and agents : Claude Sonnet 5 For more information, see the Available Models page .
Agent evaluations support for the Agent Development Kit (ADK), previously in preview, is now removed.
To evaluate agents, use agent evaluations via the DigitalOcean Control Panel for supported agent types.
To monitor ADK agent behavior, use Agent Metrics and Runtime Logs .
Insights, agent tracing, and conversation logs are deprecated for all agents, including agents created through the Control Panel, CLI, API, and Agent Development Kit (ADK).
To monitor deployed agent behavior, use Agent Metrics and Runtime Logs instead.
The Agent Evaluations MCP server tool has been renamed to Evaluations .
Custom metrics are now available for DigitalOcean Evaluations .
You can define your own metrics to evaluate model behavior against criteria specific to your use case.
DigitalOcean Evaluations is now generally available.
Use Evaluations to create test cases, run evaluation datasets, and measure model performance against selected metrics.
Presets are now available for DigitalOcean Evaluations .
You can save and reuse evaluation configurations, including the candidate model, system prompt, hyperparameters, judge model, and metrics.
Model Evaluations is now renamed to DigitalOcean Evaluations .
29 June Serverless Inference now requires a positive prepaid account balance before you can send inference requests.
Usage charges are deducted from this balance, and access is suspended if it reaches $0.
You can add a prepayment manually or enable auto-reload to replenish your balance automatically.
For more information, see Manage Serverless Inference Prepayment .
The DigitalOcean Control Panel now supports light and dark themes.
From the profile menu in the top right corner of the control panel, you can set your theme to a light or dark appearance, or match your operating system’s appearance setting.
25 June You can now attach Network File Storage shares to multiple VPC networks, and expose specific subdirectories to single VPC networks by creating access points.
A share can connect to up to 10 VPC networks in the same region.
Access points restrict clients to a specific path within the share, and are isolated from one another so that clients on one cannot see the directories governed by another.
This lets you host multiple tenants on a single share, each scoped to their own directory.
For details, see How to Create and Delete Network File Storage Access Points .
Released v1.163.0 of doctl , the official DigitalOcean CLI.
This release adds a vector-databases command group for managing vector databases .
24 June Single sign-on (SSO) with OIDC for DigitalOcean Kubernetes (DOKS) clusters is now in general availability .
You can authenticate users to your Kubernetes clusters through an identity provider like Auth0, authentik, JumpCloud, Keycloak, or Okta, instead of using token-based authentication.
SSO is configured per cluster with an issuer URL and client ID from your identity provider.
You can enable it using doctl , the DigitalOcean API , or Terraform .
The following Z.ai model is now available on DigitalOcean Inference for serverless inference , dedicated inference , Agent Development Kit , and agents : GLM-5.1 For more information, see the Available Models page .
A Fedora 44 ( fedora-44-x64 ) Droplet base image is now available in the Control Panel and through the API.
22 June The following Z.ai model is now available on DigitalOcean Inference for serverless inference , dedicated inference , Agent Development Kit , and agents : GLM-5.2 For more information, see the Available Models page .
18 June To comply with Peru’s tax regulation for digital services , DigitalOcean charges Value Added Tax (VAT) for customers with a tax location in Peru, beginning on 1 June 2026.
These charges appear on invoices issued on and after 1 July 2026.
Learn more about taxes in Peru .
17 June The following Xiaomi model is now available on DigitalOcean Inference for serverless inference , dedicated inference , Agent Development Kit , and agents : MiMo-V2.5-Pro For more information, see the Available Models page .
DigitalOcean Inference supports server-side tools on serverless inference, dedicated inference, and inference routers.
You can add the following tools: Web search, web fetch, knowledge base retrieval, and remote MCP server tools to your requests in the Chat Completions and Responses APIs.
Provider-native tools such as bash, text editor, computer use, and web fetch for Anthropic models with the Messages API .
Function calling and tool search for OpenAI models on the Responses API, and Anthropic models on the Messages API.
Web search and web fetch are in public preview .
For more information, see Use Server-Side Tools .
Updated CentOS Stream 9 and CentOS Stream 10 ( centos-stream-9-x64 , centos-stream-10-x64 ) Droplet base images require a minimum Droplet size of s-1vcpu-1gb .
You cannot create Droplets with these images on the s-1vcpu-512mb-10gb plan because the image exceeds the available disk size for that plan.
For more information, see Linux Images for Droplets .
16 June Released v1.162.0 of doctl , the official DigitalOcean CLI.
This release adds support for the PostgreSQL and MySQL Advanced Edition engines, advanced_pg and advanced_mysql , in the databases commands.
15 June The following Anthropic models are deprecated from DigitalOcean Inference as of 15 June 2026: Claude Opus 4 Claude Sonnet 4 Migrate to Claude Opus 4.8 ( anthropic-claude-opus-4.8 ) and Claude Sonnet 4.6 ( anthropic-claude-4.6-sonnet ), respectively, to avoid service disruption.
For information on our model deprecation policy and recommended replacement models, see Model Support Policy .
12 June The following Xiaomi model is now available on DigitalOcean Inference for serverless inference , Agent Development Kit , and agents : MiMo-V2.5 For more information, see the Available Models page .
Claude Fable 5 is no longer available on DigitalOcean Inference.
Access to all other Anthropic models remains available.
For more information, see the Anthropic statement on Claude Fable 5 .
10 June We support passthrough tool search on the Messages API for Anthropic models and the Responses API for OpenAI models, enabling deferred loading of tools in agentic workflows.
There is no additional cost to using tool search.
For more information, see Tool Search .
Debian 12 reached end of life on 10 June 2026.
Per our image deprecation policy , this image is available exclusively via the API for the next 30 days before we remove it from our platform.
9 June The following Anthropic model is now available on DigitalOcean Inference for serverless inference , dedicated inference , Agent Development Kit , and agents : Claude Fable 5 For more information, see the Available Models page .
In this article...
Release Notes Company About Careers Blog Docs Docs Home API Reference CLI Reference Release Notes llms.txt Trust Platform Community Tutorials Q&A Write for DOnations Currents Research Legal Code of Conduct Support Support Center Report Abuse © 2026 DigitalOcean, LLC.
All rights reserved We can't find any results for your search.
Try using different keywords or simplifying your search terms.
