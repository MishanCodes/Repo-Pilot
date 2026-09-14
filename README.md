# RepoPilot — AI Codebase Analysis & Debugging Assistant

# RepoPilot — AI Codebase Analysis & Debugging Assistant

## Live Demo : (https://repo-pilot-8219.onrender.com/)
## GitHub Repository: (https://github.com/MishanCodes/Repo-Pilot)


RepoPilot takes a source-code repository as a `.zip`, parses it into functions and classes, performs deterministic static analysis for Python, and lets you ask natural-language questions about the codebase — with answers grounded in retrieved source code rather than guesses.

The project combines traditional code analysis with an LLM layer to help developers understand unfamiliar repositories, locate relevant implementation details, and interpret detected issues.

---

## Why it's built this way

Many "AI codebase assistant" demos simply dump an entire repository into an LLM prompt and ask it to find bugs or explain the project.

That approach is easy to build, but it can produce hallucinated issues, miss important code, and make it difficult to distinguish verified findings from model-generated assumptions.

RepoPilot splits the problem into two main parts:

### 1. Deterministic analysis

No LLM is required for the core repository analysis.

* `parser.py` uses Python's `ast` module to break Python files into real syntactic units such as functions and classes rather than arbitrary line chunks.
* `static_checks.py` runs `pyflakes`, `radon`, and custom AST-based heuristics.
* Static checks identify issues such as undefined names, unused imports, high cyclomatic complexity, bare `except:`, mutable default arguments, and `== None`.
* These findings are generated from the actual code and are reproducible between runs.

### 2. Retrieval + LLM layer

The LLM is used for natural-language understanding and explanation rather than being the sole source of truth.

* `retrieval.py` builds a TF-IDF index over repository chunks.
* User questions are matched against functions, classes, documentation, source code, and file paths.
* Relevant code chunks are selected before an LLM request is made.
* `llm.py` sends the retrieved context to the configured LLM.
* The LLM explains the retrieved code, answers repository questions, generates an architecture overview, and explains static-analysis findings.

The important design principle is:

> **RepoPilot uses deterministic analysis for findings and retrieval-grounded LLM reasoning for explanations.**

The LLM augments the analysis; it does not replace it.

---

## Architecture

```text
                         .zip Repository
                              │
                              ▼
                     ┌─────────────────┐
                     │    parser.py    │
                     │                 │
                     │ AST + file      │
                     │ type parsing    │
                     └────────┬────────┘
                              │
                    ┌─────────┴─────────┐
                    │                   │
                    ▼                   ▼
             ┌──────────────┐    ┌──────────────────┐
             │ retrieval.py │    │ static_checks.py │
             │              │    │                  │
             │ TF-IDF       │    │ Pyflakes         │
             │ code search  │    │ Radon            │
             │              │    │ AST heuristics   │
             └──────┬───────┘    └────────┬─────────┘
                    │                     │
                    │                     ▼
                    │              Finding objects
                    │                     │
                    └──────────┬──────────┘
                               │
                               ▼
                         ┌───────────┐
                         │  llm.py   │
                         │           │
                         │   Groq    │
                         └─────┬─────┘
                               │
                               ▼
                  ┌─────────────────────────┐
                  │ Natural-language output │
                  │                         │
                  │ • Q&A                   │
                  │ • Explanations          │
                  │ • Overview               │
                  │ • Repository summary     │
                  └────────────┬────────────┘
                               │
                               ▼
                       ┌──────────────┐
                       │   app.py     │
                       │ Flask server │
                       │ + Web UI     │
                       └──────────────┘
```

---

## How a Question Works

For example, when a user asks:

> **"Explain the architecture of this project."**

RepoPilot follows this flow:

```text
User Question
      │
      ▼
TF-IDF Retrieval
      │
      ▼
Relevant repository chunks
      │
      ├── README.md
      ├── app.py
      ├── calculator.py
      └── other relevant functions/classes
      │
      ▼
llm.py
      │
      ▼
Groq LLM
      │
      ▼
Grounded explanation
```

The retrieved source is included in the LLM context together with file paths and function/class names.

This gives the model actual repository context instead of relying only on information from the question itself.

---

## Features

### 🔍 Retrieval-grounded codebase Q&A

Ask natural-language questions about the uploaded repository.

Examples:

```text
Explain the architecture of this project
```

```text
Where is the main entry point?
```

```text
How does authentication work?
```

```text
Which file handles database connections?
```

```text
Explain how data flows through this application
```

```text
What does this function do?
```

The same retrieval-grounded Q&A pipeline handles both typed questions and suggested questions in the interface.

---

### 🐛 Deterministic Python static analysis

RepoPilot performs static analysis independently of the LLM.

It currently uses:

* `pyflakes`
* `radon`
* Custom AST-based heuristics

Examples of detected patterns include:

* Undefined names
* Unused imports
* High cyclomatic complexity
* Bare `except:`
* Mutable default arguments
* `== None` instead of `is None`

Findings are represented with information such as:

```text
File
Line
Category
Severity
Message
```

The LLM can then explain a specific finding in plain language and suggest a fix.

---

### 📍 "Show me where"

RepoPilot does not only return a file name.

Static-analysis findings and retrieved Q&A sources can be linked back to the relevant function or class.

The application can fetch the exact source chunk covering a specific file and line through:

```text
/api/source_at
```

This allows the UI to show the actual source behind a finding or answer.

---

### 🏗️ Project overview

During repository analysis, RepoPilot detects:

* Language/file-type distribution
* Framework hints
* Manifest files
* Top-level repository structure

The LLM uses these detected signals to generate a short architecture-level overview.

The overview is based on information extracted from the repository rather than asking the LLM to invent an architecture.

---

### 📦 Multi-language repository indexing

RepoPilot can collect and index:

```text
.py
.js
.jsx
.ts
.tsx
.java
.c
.cpp
.h
.hpp
.md
.json
.yaml
.yml
```

Python files receive AST-based parsing.

Other supported languages use best-effort regex-based extraction for functions/classes where applicable, while files that cannot be structurally chunked can still be indexed as whole files.

**Deterministic static bug analysis remains Python-specific.**

---

### 🛡️ Safe ZIP handling

Uploaded ZIP archives are checked for unsafe paths before extraction to reduce the risk of ZIP path traversal attacks.

The application also:

* Limits uploads to 25 MB
* Validates ZIP files
* Rejects unsupported file types
* Returns clear API errors for invalid uploads
* Cleans previous temporary repository data

---

### ⚡ Retrieval fallback

TF-IDF is effective when user questions share meaningful vocabulary with repository code.

However, broad questions such as:

> "Explain the architecture of this project"

may not have strong lexical overlap with function names.

RepoPilot therefore uses fallback retrieval to provide useful repository context even when direct TF-IDF similarity is weak.

This helps general architecture and codebase-understanding questions reach the LLM with relevant source context.

---

## LLM Integration

RepoPilot currently uses **Groq** for the LLM layer.

The integration uses Groq's OpenAI-compatible API interface, allowing the application to use the familiar Python OpenAI client while sending requests to Groq.

The LLM is used for:

* Repository Q&A
* Finding explanations
* Architecture overview generation
* Repository health summaries

The default configured model is:

```text
openai/gpt-oss-20b
```

The model can be changed through the `REPOPILOT_MODEL` environment variable.

---

## Running It

### 1. Clone the repository

```bash
git clone <your-github-repository-url>
cd RepoPilot
```

### 2. Create a virtual environment

Windows:

```powershell
python -m venv venv
```

Activate it:

```powershell
venv\Scripts\activate
```

### 3. Install dependencies

```powershell
pip install -r requirements.txt
```

If required:

```powershell
pip install flask python-dotenv openai scikit-learn pyflakes radon
```

### 4. Configure Groq

Create a `.env` file in the project root:

```env
GROQ_API_KEY=your_groq_api_key_here
REPOPILOT_MODEL=openai/gpt-oss-20b
```

Get a Groq API key from the Groq console:

https://console.groq.com/keys

**Never commit your `.env` file or API key to GitHub.**

Add the following to `.gitignore`:

```gitignore
.env
__pycache__/
*.pyc
venv/
.venv/
```

### 5. Start the application

```powershell
python app.py
```

Then open:

```text
http://localhost:5000
```

---

## No API Key Mode

RepoPilot is designed to fail gracefully when an LLM API key is not configured.

Without a Groq API key:

* Repository parsing still works
* File indexing still works
* TF-IDF retrieval still works
* Static analysis still works
* Findings can still be displayed

LLM-dependent features return a clearly labelled message instead of crashing the application.

This makes the core analysis pipeline usable even when the external LLM service is unavailable.

---

## API Endpoints

| Endpoint         | Method | Purpose                                   |
| ---------------- | ------ | ----------------------------------------- |
| `/`              | GET    | Web interface                             |
| `/api/analyze`   | POST   | Upload and analyze repository             |
| `/api/ask`       | POST   | Ask a question about the repository       |
| `/api/findings`  | GET    | Retrieve static-analysis findings         |
| `/api/explain`   | POST   | Explain a specific finding                |
| `/api/overview`  | GET    | Retrieve project architecture overview    |
| `/api/source_at` | GET    | Retrieve source around a specific finding |
| `/api/health`    | GET    | Application and LLM availability check    |

---

## Example API Request

### Ask a question

```json
{
  "question": "Explain the architecture of this project"
}
```

The response contains the generated answer together with source information used as context.

---

## Project Structure

```text
RepoPilot/
│
├── app.py
├── parser.py
├── retrieval.py
├── static_checks.py
├── llm.py
│
├── templates/
│   └── index.html
│
├── static/
│   └── ...
│
├── requirements.txt
├── .env
├── .gitignore
└── README.md
```

| File                   | Responsibility                                                       |
| ---------------------- | -------------------------------------------------------------------- |
| `app.py`               | Flask server, API endpoints, repository state and application flow   |
| `parser.py`            | Repository parsing, code chunking, stack detection and source lookup |
| `retrieval.py`         | TF-IDF indexing, similarity search and retrieval fallback            |
| `static_checks.py`     | Pyflakes, Radon and custom static-analysis checks                    |
| `llm.py`               | Groq LLM integration for Q&A, explanations and summaries             |
| `templates/index.html` | Web interface                                                        |
| `requirements.txt`     | Python dependencies                                                  |
| `.env`                 | Local API configuration                                              |

---

## Current Scope

These limitations are intentional design choices for the current portfolio/demo version.

### Python-focused static analysis

Full deterministic static analysis is currently available for Python.

Other supported languages can be indexed and searched, but do not receive the same static-analysis pipeline.

Building reliable AST-based analysis for every supported language would significantly increase the project's scope.

### ZIP upload only

The current version accepts repository ZIP files.

GitHub URL ingestion is not currently implemented.

### Single active repository

Repository state is kept in memory and only one active repository is maintained per Flask process.

This keeps the application simple and is appropriate for the current portfolio/demo scope.

### TF-IDF retrieval

RepoPilot currently uses TF-IDF rather than neural embeddings.

For a small repository corpus, TF-IDF provides:

* Fast retrieval
* Low infrastructure requirements
* Deterministic behavior
* Strong lexical matching for code identifiers

The retrieval layer is structured so that an embedding-based implementation could be introduced later.

### LLM context limitation

The LLM only receives the retrieved repository context.

If the relevant implementation is not present in the retrieved context, the model is instructed not to invent an answer.

---

## What I'd Add Next

Potential future improvements include:

* Real AST/tree-sitter based chunking for JavaScript/TypeScript
* GitHub URL ingestion
* Neural/vector embeddings for semantic retrieval
* Multi-file bug detection
* Cross-file type and dependency analysis
* Persistent repository storage
* Repository comparison over time
* Dependency/security scanning
* Automated test generation
* Dependency graphs
* Authentication and multi-user support
* Background processing for large repositories
* Docker deployment
* CI/CD integration

---

## Design Philosophy

The central design principle behind RepoPilot is:

> **Use deterministic program analysis where possible and use the LLM where natural-language reasoning is useful.**

The system therefore follows:

```text
Parse
  ↓
Index
  ↓
Retrieve
  ↓
Analyze
  ↓
Provide Evidence
  ↓
Explain with LLM
```

This separation makes the application easier to debug and explain.

It also makes it possible to distinguish between:

**Verified analysis**

```text
"Pyflakes detected an undefined name at line 24."
```

and:

**LLM interpretation**

```text
"This probably occurs because the variable is referenced
before it is defined."
```

The first comes from deterministic analysis.

The second is generated by the LLM using the provided finding.

---

## What I Learned

Building RepoPilot involved practical work across several areas of software and AI engineering:

* Python AST-based code parsing
* Flask REST API development
* Repository processing
* Code chunking
* TF-IDF information retrieval
* Cosine similarity
* Retrieval-grounded LLM applications
* Static code analysis
* Prompt design
* Groq API integration
* Error handling and API fallback
* ZIP security and path traversal protection
* Source-code location tracking
* Designing modular AI-assisted developer tools

---

## Portfolio Highlights

RepoPilot demonstrates the combination of:

```text
Traditional Software Engineering
              +
Static Code Analysis
              +
Information Retrieval
              +
LLM Integration
              =
AI-Assisted Developer Tool
```

The project intentionally avoids treating an LLM as a replacement for traditional analysis.

Instead, RepoPilot combines deterministic tooling with retrieval-grounded LLM reasoning to provide a more explainable approach to AI-assisted codebase understanding.

---

## Author

**Mishanraj Kalita**

B.Tech Computer Science & Engineering

Areas of interest:

* AI/ML Engineering
* Generative AI
* Large Language Models
* Retrieval-Augmented Generation
* Python Backend Development
* Machine Learning
* Developer Tools


