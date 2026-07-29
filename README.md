<div align="center">

# 🚀 Intelligent-Dual-modality-Desktop-Automation-AI-Assistant
An intelligent hands-free desktop assistant combining multilingual voice interaction, computer vision, LLM-powered conversation, and desktop automation.


<img src="docs/demo.gif" width="90%"/>

![Python](https://img.shields.io/badge/Python-3.10-blue)
![React](https://img.shields.io/badge/React-18-61DAFB)
![Electron](https://img.shields.io/badge/Electron-Desktop-47848F)
![FastAPI](https://img.shields.io/badge/FastAPI-Backend-009688)
![OpenCV](https://img.shields.io/badge/OpenCV-ComputerVision-5C3EE8)
![MediaPipe](https://img.shields.io/badge/MediaPipe-HandTracking-orange)
![Transformers](https://img.shields.io/badge/HuggingFace-Transformers-yellow)
![LLM](https://img.shields.io/badge/LLM-Integrated-success)

</div>

---

# 📖 Overview

This project is an **AI-powered desktop assistant** that enables users to control a Windows computer naturally through **multilingual voice interaction** and **real-time hand gesture recognition**.

Unlike conventional desktop assistants that rely on predefined commands or single interaction methods, this system combines **Natural Language Understanding**, **Computer Vision**, **Desktop Automation**, and **Large Language Models** into a unified desktop application capable of intelligent conversation and operating system control.

The project was developed as a Final Year Project and follows modern software engineering principles including **Layered Architecture**, **Separation of Concerns (SoC)**, **modular backend orchestration**, and **real-time event-driven communication**.

---

# ✨ Key Features

## 🎙️ Multilingual Voice Interaction

- English & Chinese speech recognition
- Automatic language handling
- Natural language conversation
- Voice-controlled desktop operations
- Text-to-Speech response generation

---

## 🧠 Intelligent Intent Understanding

Instead of using traditional rule-based command matching, the system uses

- DeBERTa Zero-shot Intent Routing
- Natural Language Inference (NLI)
- Confidence-based decision making
- Safe fallback mechanisms
- Command clarification handling

The assistant intelligently determines whether a request should be

- 💻 Execute a desktop operation
- 💬 Generate an AI response

without requiring model retraining.

---

## 🖐️ Vision-based Gesture Control

Real-time webcam hand tracking enables

- Cursor movement
- Left / Right click
- Double click
- Drag & Drop
- Scrolling
- Volume control
- Brightness control
- Zoom
- Screenshot
- Multiple configurable gestures

Optimized pointer control includes

- Increased FPS
- Reduced gesture overlay
- Low-latency cursor movement
- Responsive real-time interaction

---

## 🤖 AI Assistant

Supports

- General conversation
- Question answering
- Reasoning
- Content explanation
- Knowledge retrieval
- Productivity assistance

through integrated Large Language Models.

---

## 🖥️ Desktop Automation

The assistant performs operating system tasks including

- Opening applications
- Window control
- Keyboard shortcuts
- File Explorer navigation
- Browser automation
- System settings
- Clipboard interaction
- Media control

using deterministic desktop automation for improved safety.

---

# 🏗️ System Architecture

```
User
 │
 ├───────────────┐
 │               │
Voice         Gesture
 │               │
ASR        Hand Tracking
 │               │
Language      Gesture
Handling     Recognition
 │               │
 └──────┬────────┘
        │
 Backend Orchestrator
        │
 Intent Routing
 (DeBERTa Zero-shot)
        │
 ┌──────────────┬──────────────┐
 │              │              │
Desktop      LLM Chat      Feedback
Automation   Response      Logging
        │
 React + Electron Desktop
```

---

# ⚙️ Technology Stack

## Frontend

- React 18
- TypeScript
- Electron
- TailwindCSS

---

## Backend

- Python
- FastAPI
- WebSocket
- AsyncIO

---

## AI & Machine Learning

- Hugging Face Transformers
- DeBERTa Zero-shot Classification
- Whisper
- Google Speech Recognition
- Large Language Models

---

## Computer Vision

- OpenCV
- MediaPipe Hands

---

## Desktop Control

- PyAutoGUI
- PyCAW
- Screen Brightness Control
- Windows APIs

---

## Engineering Principles

- Layered Architecture
- Separation of Concerns (SoC)
- Modular Design
- Event-driven Communication
- Confidence-based Routing
- Fallback Architecture
- Audit Logging
- Real-time Processing

---

# 📊 Technical Highlights

✔ Modular full-stack desktop architecture

✔ Event-driven backend orchestration

✔ Real-time WebSocket communication

✔ AI-powered zero-shot intent classification

✔ Natural language desktop automation

✔ Multilingual speech interaction

✔ Vision-guided gesture recognition

✔ Responsive desktop UI

✔ Configurable user preferences

✔ Safe deterministic command execution

✔ Extensible architecture for future AI models

---

# 📈 Project Outcomes

The completed system successfully demonstrates

- High speech recognition accuracy
- Reliable intent routing
- Responsive gesture interaction
- Low-latency desktop automation
- Positive usability evaluation
- Modular and maintainable software architecture

The project illustrates how modern AI technologies can be integrated into a production-style desktop application while maintaining scalability, maintainability, and user-centred interaction.

---

# 💼 Software Engineering Skills Demonstrated

This project showcases practical experience in

### Full Stack Development

- Frontend Engineering
- Backend API Development
- Desktop Application Development
- REST APIs
- WebSocket Communication

### Software Engineering

- System Design
- Layered Architecture
- SOLID-inspired modular design
- Separation of Concerns
- Real-time Systems
- Performance Optimization
- Error Handling
- Logging
- Testing & Evaluation

### Artificial Intelligence

- Natural Language Processing
- Zero-shot Classification
- Speech Recognition
- Computer Vision
- Human-Computer Interaction
- Large Language Models

---

# 🚀 Future Improvements

- True multimodal voice-gesture fusion
- Additional language support
- Multi-camera gesture tracking
- Offline LLM support
- Cloud synchronization
- Plugin-based command extensions
- Accessibility-focused enhancements

---

# 👨‍💻 Author

**Lee Shan Yue**

Bachelor of Computer Science and Technology

Xiamen University Malaysia
