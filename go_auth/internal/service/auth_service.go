package service

import "go_auth/internal/token"

type AuthService struct{}

func (s *AuthService) Login(email, password string) (string, error) {

	userID := "123"
	return token.Generate(userID, email)
}
