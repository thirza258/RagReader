package main

import (
	"github.com/gin-gonic/gin"
	"go_auth/internal/handler"
	"go_auth/internal/service"
)

func main() {
	r := gin.Default()

	authService := &service.AuthService{}
	authHandler := handler.NewAuthHandler(authService)

	r.POST("/login", authHandler.Login)

	r.Run(":8080")
}
