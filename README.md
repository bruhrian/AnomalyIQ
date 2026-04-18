<div align="center">
  <h3>National AI Student Challenge 2026 | In partnership with Huawei</h3>
  <p><i>Intelligent multi-agent system for critical infrastructure monitoring and predictive maintenance</i></p>
</div>


## 🏆 Team Agentic Bunch
- Brian Chua(@bruhrian) - Project Lead, ML & AI Engineer
- Ervin Er(@ERZXDoodles) - Backend & MCP server developer, AI Engineer
- Jiang Xu Yang(@jiangmomo24-bot) - UI/UX developer, Data & AI Engineer


## 📋 Overview
AnomalyIQ is an industrial monitoring UI that combines real-time sensor tracking, AI-assisted diagnostics, and system health checks into one unified interface. This helps operators detect issues faster and make better maintenance decisions. Our solution leverages autonomous AI agents to:

- 🔍 **Detect anomalies in real-time** across sensor networks
- 📈 **Predict equipment failures** before they occur
- 🤝 **Coordinate multi-agent responses** to complex situations
- 💡 **Provide explainable insights** for human operators


## 🎯 Key Features
1. **Multi-Agent Architecture**: Specialized agents collaborate to monitor, detect, predict, and explain system behaviors
2. **Real-Time Anomaly Detection**: Advanced pattern recognition for cyber-physical threats
3. **Predictive Maintenance**: ML models forecasting equipment degradation and failure probabilities
4. **Human-in-the-Loop Decision Support**: Explainable AI insights with actionable recommendations
5. **Interactive Dashboard**: Intuitive visualization for situational awareness


## 🏗️ System Architecture
<img width="1554" height="808" alt="image" src="https://github.com/user-attachments/assets/610224c8-d06a-4335-8450-038945e51e13" />

## 🛠️ Tech Stack
- **AI/ML Framework**: TensorFlow 
- **Agent Framework**: MCP & Langchain
- **Backend**: FastAPI / Python
- **Frontend**: React 
- **Database**: Qdrant & PostgreSQL
- **Visualization**: Matplotlib


## 🚀 Getting Started

### Prerequisites
- Python 3.9+
- Node.js 16+


### Installation
```bash
# Clone repository
git clone https://github.com/bruhrian/AnomalyIQ.git
cd AnomalyIQ

# Set up Python environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt

# Set up frontend
cd frontend
npm install
cd ..

# Configure environment variables
cp .env.example .env
# Edit .env with your configuration

Running the System
# Start backend services
python MCP & Backend/main.py

# Start frontend development server
cd Frontend
npm start
```

📊 Sample Datasets
We're using 'Real-Time IoT-Driven Production System Dataset' for training and testing:

Kaggle link: https://www.kaggle.com/datasets/programmer3/real-time-iot-driven-production-system-dataset


🧪 Testing
```bash
# Run unit tests
pytest tests/

# Run integration tests
pytest tests/integration_tests/
```

📚 Documentation
System Architecture

MCP client server

FastAPIs for backend

Setup Guide


📄 License(TBC)
This project is licensed under the MIT License - see the LICENSE file for details.


🙏 Acknowledgments
National AI Student Challenge
Huawei
