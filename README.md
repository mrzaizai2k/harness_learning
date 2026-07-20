# AI Agents Software Development Project

## Table of Contents
- [Overview](#overview)
- [What It Does](#what-it-does)
- [Project Structure](#project-structure)

## Overview
This project demonstrates the transformative role of AI agents in software development. It leverages AI-powered tools to enhance coding productivity, automate testing, assist in debugging, and improve the quality and efficiency of software engineering workflows.

## What It Does
- Integrates AI agents for automated code generation and intelligent coding assistance.
- Automates software testing and quality assurance through continuous AI monitoring.
- Provides debugging assistance to reduce developer time spent on fixing errors.
- Includes real-world examples and case studies to showcase practical AI agent applications in software development.
- Generates blog content explaining the impact and challenges of AI in the software industry.

## Project Structure
- `/blog_posts/`: Contains blog articles and technical writeups.
- `/research/`: Holds research summaries and external source data relevant to AI agents.
- `/skills/`: Contains skill-based workflows and helpers for AI content generation.
- `main.py`: Entry point for running AI-driven processes.
- `agent_runner.py`, `content_writer.py`, `tool_manager.py`: Core modules managing AI agents and content generation.

This project serves as both a research and demonstration platform for leveraging AI agents in software development workflows, aimed at developers and technology leaders interested in AI-driven productivity improvements.

## How to run
BE:
```bash
    uvicorn main:app --reload --port 8000
```

FE:
```bash
    cd frontend
    npm run dev
```
Subagent
```bash

docker build -t infotainment_agent agents/infotainment

docker run -d \
  --name infotainment_agent \
  -p 8004:8004 \
  --add-host=host.docker.internal:host-gateway \
  --env-file ./.env \
  -v "$(pwd)/agents/infotainment:/app" \
  infotainment_agent
```