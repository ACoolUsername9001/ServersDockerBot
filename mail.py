from email.message import EmailMessage
from smtplib import SMTP_SSL, SMTP_SSL_PORT


class MailClient:
    def __init__(self, username: str, password: str, domain: str):
        self._username = username
        self._password = password
        self._domain = domain
        self._smtp = SMTP_SSL(domain, SMTP_SSL_PORT, timeout=5)
        self._smtp.login(user=username, password=password)
    

    def send_message(self, destination: str, subject: str, content: str):
        msg = EmailMessage()
        msg.set_content(content)
        msg['Subject'] = subject
        msg['From'] = self._username
        msg['To'] = destination
        
        self._smtp.send_message(msg)
    
    def quit(self):
        self._smtp.quit()