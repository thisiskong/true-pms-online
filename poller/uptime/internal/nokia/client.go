// Package nokia implements a REST client for polling Nokia Altiplano-managed
// devices (device-manager REST/RESTCONF API) as an alternative to SNMP.
package nokia

import (
	"context"
	"crypto/tls"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"time"
)

// Config holds connection settings for the Altiplano REST controller.
type Config struct {
	BaseURL     string
	Username    string
	Password    string
	Timeout     time.Duration
	Retries     int
	Concurrency int
}

// Client talks to a single Nokia Altiplano controller. All Nokia devices
// share one controller and one login session, so Client caches its bearer
// token and caps in-flight requests with a semaphore to avoid overloading it.
type Client struct {
	baseURL    string
	username   string
	password   string
	httpClient *http.Client
	sem        chan struct{}

	mu    sync.Mutex
	token string
}

// NewClient builds a Client from cfg. baseURL is used as-is (no trailing
// slash trimming assumptions beyond a simple TrimSuffix).
func NewClient(cfg Config) *Client {
	concurrency := cfg.Concurrency
	if concurrency <= 0 {
		concurrency = 1
	}
	return &Client{
		baseURL:  strings.TrimSuffix(cfg.BaseURL, "/"),
		username: cfg.Username,
		password: cfg.Password,
		httpClient: &http.Client{
			Timeout: cfg.Timeout,
			Transport: &http.Transport{
				TLSClientConfig: &tls.Config{InsecureSkipVerify: true},
			},
		},
		sem: make(chan struct{}, concurrency),
	}
}

// GetUptime fetches the device's sys-up-time counter (centiseconds) and its
// reported boot-datetime. Unlike SNMP's sysUptime, Nokia's counter is not
// bounded to 32 bits and does not wrap at ~497 days, so it's returned as a
// uint64; boot-datetime is the authoritative signal for reboot detection.
func (c *Client) GetUptime(ctx context.Context, deviceID string) (sysUpTime uint64, bootTime time.Time, err error) {
	select {
	case c.sem <- struct{}{}:
	case <-ctx.Done():
		return 0, time.Time{}, ctx.Err()
	}
	defer func() { <-c.sem }()

	base := fmt.Sprintf(
		"%s/nokia-altiplano-av/rest/restconf/data/anv:device-manager/anv-device-holders:device=%s/device-specific-data/ietf-system:system-state/clock",
		c.baseURL, url.PathEscape(deviceID),
	)

	var sysUpRaw struct {
		SysUpTime string `json:"nokia-ietf-system-aug:sys-up-time"`
	}
	if err := c.getJSON(ctx, base+"/nokia-ietf-system-aug:sys-up-time", &sysUpRaw); err != nil {
		return 0, time.Time{}, fmt.Errorf("get sys-up-time: %w", err)
	}
	v, err := strconv.ParseUint(sysUpRaw.SysUpTime, 10, 64)
	if err != nil {
		return 0, time.Time{}, fmt.Errorf("parse sys-up-time %q: %w", sysUpRaw.SysUpTime, err)
	}
	sysUpTime = v

	var bootRaw struct {
		BootDatetime string `json:"ietf-system:boot-datetime"`
	}
	if err := c.getJSON(ctx, base+"/boot-datetime", &bootRaw); err != nil {
		return 0, time.Time{}, fmt.Errorf("get boot-datetime: %w", err)
	}
	bootTime, err = time.Parse(time.RFC3339, bootRaw.BootDatetime)
	if err != nil {
		return 0, time.Time{}, fmt.Errorf("parse boot-datetime %q: %w", bootRaw.BootDatetime, err)
	}

	return sysUpTime, bootTime, nil
}

// getJSON performs an authenticated GET and decodes the JSON body into out.
// On a 401 it invalidates the cached token, logs in again, and retries once.
func (c *Client) getJSON(ctx context.Context, urlStr string, out any) error {
	token, err := c.ensureToken(ctx)
	if err != nil {
		return err
	}

	status, body, err := c.doGet(ctx, urlStr, token)
	if err != nil {
		return err
	}
	if status == http.StatusUnauthorized {
		c.invalidateToken(token)
		token, err = c.ensureToken(ctx)
		if err != nil {
			return err
		}
		status, body, err = c.doGet(ctx, urlStr, token)
		if err != nil {
			return err
		}
	}
	if status != http.StatusOK {
		return fmt.Errorf("unexpected status %d from %s", status, urlStr)
	}
	if err := json.Unmarshal(body, out); err != nil {
		return fmt.Errorf("decode response: %w", err)
	}
	return nil
}

func (c *Client) doGet(ctx context.Context, urlStr, token string) (int, []byte, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, urlStr, nil)
	if err != nil {
		return 0, nil, err
	}
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Accept", "application/yang-data+json")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return 0, nil, err
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return 0, nil, fmt.Errorf("read response body: %w", err)
	}
	return resp.StatusCode, body, nil
}

// ensureToken returns the cached token, logging in if none is cached yet.
func (c *Client) ensureToken(ctx context.Context) (string, error) {
	c.mu.Lock()
	if c.token != "" {
		t := c.token
		c.mu.Unlock()
		return t, nil
	}
	c.mu.Unlock()

	return c.login(ctx)
}

// invalidateToken clears the cached token if it still matches stale, so a
// concurrent goroutine that already refreshed it doesn't get clobbered.
func (c *Client) invalidateToken(stale string) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.token == stale {
		c.token = ""
	}
}

func (c *Client) login(ctx context.Context) (string, error) {
	c.mu.Lock()
	defer c.mu.Unlock()

	// Another goroutine may have already logged in while we waited for the lock.
	if c.token != "" {
		return c.token, nil
	}

	form := url.Values{
		"j_username": {c.username},
		"j_password": {c.password},
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost,
		c.baseURL+"/nokia-altiplano-ac/rest/auth/login", strings.NewReader(form.Encode()))
	if err != nil {
		return "", err
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return "", fmt.Errorf("login request: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", fmt.Errorf("read login response: %w", err)
	}
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("login failed: status %d", resp.StatusCode)
	}

	var loginResp struct {
		AccessToken string `json:"accessToken"`
	}
	if err := json.Unmarshal(body, &loginResp); err != nil {
		return "", fmt.Errorf("decode login response: %w", err)
	}
	if loginResp.AccessToken == "" {
		return "", fmt.Errorf("login response missing accessToken")
	}

	c.token = loginResp.AccessToken
	return c.token, nil
}
