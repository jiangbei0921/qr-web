pip install gunicorn
set BASE_URL=https://yourdomain.com
gunicorn -w 4 -b 0.0.0.0:5000 app:app
