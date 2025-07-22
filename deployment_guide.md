# Deployment Guide: PriceLabs Streamlit App

This guide explains how to deploy and run the PriceLabs adjustment tool, both locally and on [Streamlit Cloud](https://share.streamlit.io/).

---

## 📁 Project Structure

```
magic boxes/k_pricelabs5%_new/
│
├── streamlit_app.py                # Main Streamlit app (in project root)
├── pricelabs_tool/                 # Business logic and helpers
│   ├── __init__.py
│   ├── api_client.py
│   ├── price_calculator.py
│   ├── config.py
│   └── ... (other helpers, if needed)
├── requirements.txt                # All dependencies
├── .gitignore                      # Should include .env, venv/, etc.
├── .env                            # (Not tracked by git) Your secrets and API keys
├── deployment_guide.md             # This file
└── ... (other docs, configs, etc.)
```

---

## 🛠️ Prerequisites
- Python 3.8+
- [Streamlit](https://streamlit.io/)
- [Git](https://git-scm.com/)
- A PriceLabs API key

---

## 🔑 Environment Variables
Create a `.env` file in your project root (this is git-ignored):

```
PRICELABS_API_KEY=your_pricelabs_api_key_here
API_BASE_URL=https://api.pricelabs.co/v1
```

---

## 📦 Installing Dependencies

```sh
pip install -r requirements.txt
```

---

## ▶️ Running Locally

**You must set the `PYTHONPATH` to your project root before running Streamlit:**

### On macOS/Linux:
```sh
export PYTHONPATH=$(pwd)
streamlit run streamlit_app.py
```

### On Windows (cmd):
```cmd
set PYTHONPATH=%cd%
streamlit run streamlit_app.py
```

---

## ☁️ Deploying to Streamlit Cloud

1. **Push your code to GitHub.**
2. **Create a new app on [Streamlit Cloud](https://share.streamlit.io/).**
3. **Set the main file to:**
   ```
   streamlit_app.py
   ```
4. **Set environment variables:**
   - In the app settings, add your `PRICELABS_API_KEY` and (optionally) `API_BASE_URL` as secrets.
5. **Set the Python path:**
   - In “Advanced settings”, set the Python path to `.` (the project root), or add `export PYTHONPATH=$(pwd)` as a pre-run command if the platform allows.
6. **Deploy!**

---

## 🔒 Security Notes
- **Never commit your `.env` file or secrets to git.**
- `.gitignore` should include `.env`, `venv/`, `.venv/`, etc.
- All secrets are loaded from environment variables at runtime.

---

## 🐞 Troubleshooting

### ModuleNotFoundError for `pricelabs_tool`
- Make sure you set `PYTHONPATH` as shown above.
- On Streamlit Cloud, set the Python path to `.` or use a pre-run command.
- Ensure `streamlit_app.py` is in the project root, not in a subfolder.

### API Key Errors
- Make sure your `PRICELABS_API_KEY` is set in your environment or Streamlit Cloud secrets.

### Other Issues
- Check logs in Streamlit Cloud (“Manage app” > “Logs”).
- Ensure all dependencies are in `requirements.txt`.

---

## ✅ Best Practices
- Keep business logic in `pricelabs_tool/`.
- Only UI code in `streamlit_app.py`.
- Use environment variables for all secrets.
- Test locally before deploying.

---

Happy deploying! 🚀 