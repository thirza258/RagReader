package token

import (
	"time"
	"os"
	"github.com/golang-jwt/jwt/v5"
)



var secret = []byte(os.Getenv("JWT_SECRET"))

func Generate(userID, email string) (string, error) {
	claims := jwt.MapClaims{
		"sub": userID,
		"email": email,
		"iss": "go-auth",
		"exp": time.Now().Add(24 * time.Hour).Unix(),
	}

	t := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	return t.SignedString(secret)
}

func Validate(tokenStr string) (*jwt.Token, error) {
	return jwt.Parse(tokenStr, func(t *jwt.Token) (any, error) {
		return secret, nil
	})
}
