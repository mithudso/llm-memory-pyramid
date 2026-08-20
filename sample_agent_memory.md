# User Preferences and Core Project Architecture

## Development Framework
- User prefers Python for backend data analytics scripts and TypeScript for web applications.
- Always use Vanilla CSS for styling; never use TailwindCSS unless explicitly requested by the user.
- The system must enforce high-efficiency context window budgeting.

## Longterm LLM Memory System
- Concept: NapMem (Navigate over Pyramid Memory) treats long-term memory as a structured, active action space.
- NapMem organizes memory into a multi-granularity pyramid: Raw Conversations, Memory Records, Topic Tracks, and User Profiles.
- Agents use Group Relative Policy Optimization (GRPO) reinforcement learning to navigate their own memory layers.
- Problem: Passive RAG context dumping leads to lost-in-the-middle phenomena and high token waste.
- Solution: Document Distiller extracts atomic units (concept, fact, actionable, question, problem, statement, quote, idea) with source anchors.
- Actionable: Always run document-distiller --diff on updated memory files during background naptime processing.

## Verification & Constraints
- Fact: provenances must link Layer 1 records back to exact Layer 0 line numbers.
- Idea: We could build an automated background daemon that triggers memory distillation whenever the agent goes idle for > 5 minutes.
- Question: How does NapMem handle conflicting user preferences updated across different sessions?
