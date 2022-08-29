FROM alpine
EXPOSE 25565
ARG minecraft_version='vanila/latest'
ARG mods=''
ENTRYPOINT ["java", "-jar", "server.jar"]
# CMD ["-Xms1024M", "-Xmx2048M"]
RUN addgroup runner && adduser -D -h /opt/minecraft/runner -s /bin/sh -G runner runner
RUN apk update && apk upgrade && apk add --no-cache openjdk17
WORKDIR /opt/minecraft/runner
COPY minecraft_servers/${minecraft_version}.jar ./server.jar
COPY minecraft_servers/eula.txt ./eula.txt
