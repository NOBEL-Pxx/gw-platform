#!/bin/sh
cd /home/gravitational-wave-backend
exec java -Dhttps.protocols=TLSv1.2,TLSv1.3 -Djdk.tls.client.protocols=TLSv1.2,TLSv1.3 -jar app.jar
